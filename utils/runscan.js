import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function runPython(script, args) {
return new Promise((resolve, reject) => {
const child = spawn("python3", [script, ...args]);


let stdout = "";
let stderr = "";

child.stdout.on("data", (data) => {
  stdout += data.toString();
});

child.stderr.on("data", (data) => {
  stderr += data.toString();
});

child.on("close", () => {
  if (stderr) {
    console.warn(`[python3 stderr] ${script}:\n${stderr}`);
  }

  try {
    const parsed = JSON.parse(stdout.trim());

    if (parsed?.error) {
      return reject({ message: parsed.error, stderr });
    }

    resolve(parsed);
  } catch {
    reject({
      message: "Invalid JSON from Python",
      raw: stdout.slice(0, 500),
      stderr: stderr.slice(0, 500),
    });
  }
});

child.on("error", (err) => {
  reject({ message: err.message });
});


});
}

export async function runScanner(repoPath, userType = null) {
try {
const absolutePath = path.resolve(repoPath);

const detectorPath = path.join(__dirname, "analysis/type.py");
const analyzerPath = path.join(__dirname, "analysis/final_analysis.py");

const detected = await runPython(detectorPath, [absolutePath]);

const autoType = detected?.type || "application";
const confidence = detected?.confidence || 0;

const finalType = userType || autoType;

const analysis = await runPython(analyzerPath, [absolutePath, finalType]);

return {
  repoType: {
    autoType,
    userType: userType || null,
    finalType,
    confidence,
    overridden: Boolean(userType),
  },

  unusedFiles: Array.isArray(analysis.files)
    ? analysis.files.map((f) =>
        typeof f === "string"
          ? { path: f, confidence: 0.8 }
          : f
      )
    : [],

  unusedExports: analysis.unusedExports || [],

  unusedDeps: Array.isArray(analysis.deps)
    ? analysis.deps.map((d) =>
        typeof d === "string"
          ? { name: d, confidence: 0.8 }
          : d
      )
    : [],

  unusedCode: analysis.unusedCode || [],

  summary: {
    files: analysis.files?.length || 0,
    exports: analysis.unusedExports?.length || 0,
    deps: analysis.deps?.length || 0,
  },

  error: null,
};


} catch (error) {
console.error("[runScanner] failed:", error);


return {
  error: error,
};


}
}
