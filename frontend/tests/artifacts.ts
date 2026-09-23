// Keep a new acceptance run separate from the historical stage-7 evidence.
export const artifactPrefix = process.env.PLAYWRIGHT_ARTIFACT_PREFIX
  ?? (process.env.PLAYWRIGHT_PRODUCTION === '1' ? 'stage7' : 'current')
