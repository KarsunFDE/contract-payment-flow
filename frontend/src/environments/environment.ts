export const environment = {
  production: false,
  /** All API calls SHOULD go through this gateway URL — except the ones that don't (Item 8). */
  apiGatewayUrl: 'http://localhost:8080',
  /**
   * DEV-ONLY: AI-draft + clause-retrieval calls hit ai-orchestrator directly on its
   * published port (no dev auth server exists for the gateway path). In production
   * these route through the gateway at /api/ai/**.
   */
  aiOrchestratorUrl: 'http://localhost:8000',
};
