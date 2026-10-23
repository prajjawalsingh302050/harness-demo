// Repository settings used by the UI.
const REPO_OWNER = "prajjawalsingh302050";
const REPO_NAME = "harness-demo";
const REPO_URL = `https://github.com/${REPO_OWNER}/${REPO_NAME}`;

// Where the GitHub Action publishes health reports (the health-reports branch).
// The GitHub contents API is used instead of raw.githubusercontent.com because it is not cached.
const REPORTS_API = `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/contents`;
const REPORTS_REF = "health-reports";
