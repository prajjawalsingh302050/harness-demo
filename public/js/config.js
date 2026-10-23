// Where the GitHub Action publishes health reports (the health-reports branch).
// The GitHub contents API is used instead of raw.githubusercontent.com because it is not cached.
const REPORTS_API = "https://api.github.com/repos/Prajjawalsingh87/harness-demo/contents";
const REPORTS_REF = "health-reports";
