export function filterResults(result) {

const SAFE_FILE_NAMES = new Set([
    "index.js",
    "app.js",
    "server.js",
    "main.js",
    "package.json",
    "tsconfig.json",
    ".env"
]);

const SAFE_DIRS = [
    "config/",
    ".github/",
    "scripts/"
];

function normalizePath(p) {
    return (p || "").replace(/\\/g, "/").toLowerCase();
}

function isSafeFile(filePath) {
    const p = normalizePath(filePath);

    const fileName = p.split("/").pop();

    // exact filename match
    if (SAFE_FILE_NAMES.has(fileName)) return true;

    // directory-based protection
    if (SAFE_DIRS.some(dir => p.startsWith(dir))) return true;

    return false;
}

function validConfidence(value, min) {
    return typeof value === "number" && value >= min;
}

return {
    unusedFiles: (result?.unusedFiles || []).filter(f =>
        f &&
        validConfidence(f.confidence, 0.9) &&
        f.path &&
        !isSafeFile(f.path)
    ),

    unusedExports: (result?.unusedExports || []).filter(e =>
        e && validConfidence(e.confidence ?? 0.8, 0.85)
    ),

    unusedDeps: (result?.unusedDeps || []).filter(d =>
        d && validConfidence(d.confidence ?? 0.8, 0.95)
    )
};


}
