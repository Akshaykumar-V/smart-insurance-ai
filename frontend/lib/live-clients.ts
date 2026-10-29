import { createApiConditionClient } from "./condition-client";
import { ConditionError, type ConditionClient } from "./condition-extraction";
import type { LiveConfig } from "./app-config";
import { AuthSessionController } from "./auth-session";
import { createApiUploadClient } from "./upload-client";
import { UploadError, type UploadClient } from "./upload-contract";
import { createApiPolicyClient, type PolicyClient } from "./policy-client";
import { PolicyDataError } from "./policy-intelligence";
import { createApiWalletClient, type WalletClient } from "./wallet-client";

export function createLiveClients(config: LiveConfig, auth: AuthSessionController, ownerId: string) {
  const getAccessToken = () => auth.getAccessToken(ownerId);
  const upload = createApiUploadClient(config.backendOrigin, getAccessToken);
  const policy = createApiPolicyClient(config.backendOrigin, getAccessToken);
  const conditions = createApiConditionClient(config.backendOrigin, getAccessToken);
  const wallet = createApiWalletClient(config.backendOrigin, getAccessToken);
  async function guarded<T>(signal: AbortSignal, run: (scope: AbortSignal) => Promise<T>): Promise<T> {
    const scope = auth.requestSignal(ownerId, signal);
    try {
      const result = await run(scope);
      scope.throwIfAborted();
      return result;
    } catch (error) {
      if (!scope.aborted && ((error instanceof UploadError && error.status === 401) || (error instanceof PolicyDataError && error.status === 401) || (error instanceof ConditionError && error.status === 401))) auth.expire();
      throw error;
    }
  }
  const uploadClient: UploadClient = {
    mode: "api",
    upload: (input, signal) => guarded(signal, scope => upload.upload(input, scope)),
    getJob: (id, signal) => guarded(signal, scope => upload.getJob(id, scope)),
  };
  const policyClient: PolicyClient = {
    mode: "api",
    getPolicy: (id, signal) => {
      if (!config.policyReadsEnabled) return Promise.reject(new PolicyDataError("Live policy details are not enabled. The backend must first implement compatible v0.1 policy reads."));
      return guarded(signal, scope => policy.getPolicy(id, scope));
    },
    getFindings: (id, signal) => {
      if (!config.policyReadsEnabled) return Promise.reject(new PolicyDataError("Live findings are not enabled."));
      return guarded(signal, scope => policy.getFindings(id, scope));
    },
  };
  const walletClient: WalletClient = {
    listPolicies: signal => {
      if (!config.policyReadsEnabled) return Promise.reject(new PolicyDataError("Live policy reads are not enabled."));
      return guarded(signal ?? new AbortController().signal, scope => wallet.listPolicies(scope));
    },
  };
  function conditionGuard<T>(signal: AbortSignal, run: (scope: AbortSignal) => Promise<T>) {
    if (!config.conditionExtractionsEnabled) return Promise.reject(new ConditionError("Condition extraction is not enabled. No request was sent."));
    return guarded(signal, run);
  }
  const conditionClient: ConditionClient = {
    mode: "api",
    extract: (id, request, signal) => conditionGuard(signal, scope => conditions.extract(id, request, scope)),
    getJob: (identity, signal) => conditionGuard(signal, scope => conditions.getJob(identity, scope)),
    getRun: (identity, signal) => conditionGuard(signal, scope => conditions.getRun(identity, scope)),
  };
  // The local claim simulator remains demo-only; the backend has no live simulation endpoint in use.
  return { uploadClient, policyClient, walletClient, conditionClient, getAccessToken };
}
