// testRunner.js

import fs from "fs";
import path from "path";

const API_URL = "http://localhost:3000/analyze";

//
// 🔹 REPO GROUPS
//

const LIBRARIES = [
  "https://github.com/lodash/lodash",
  "https://github.com/axios/axios",
  "https://github.com/date-fns/date-fns",
  "https://github.com/uuidjs/uuid"
];

const FRAMEWORKS = [
  "https://github.com/angular/angular",
  "https://github.com/nestjs/nest",
  "https://github.com/vercel/next.js",
  "https://github.com/vuejs/core"
];

const APPLICATIONS = [
  "https://github.com/TryGhost/Ghost",
  "https://github.com/gothinkster/react-redux-realworld-example-app",
  "https://github.com/supabase/supabase"
];

const CLI_TOOLS = [
  "https://github.com/npm/cli",
  "https://github.com/yargs/yargs"
];

const PLUGINS = [
  "https://github.com/jsx-eslint/eslint-plugin-react",
  "https://github.com/vitejs/vite-plugin-react"
];

//
// 🔹 CSV BUILDER
//

function toCSV(data) {
  if (!data.length) return "";

  const headers = Object.keys(data[0]);

  const rows = data.map(obj =>
    headers.map(h => JSON.stringify(obj[h] ?? "")).join(",")
  );

  return [headers.join(","), ...rows].join("\n");
}

//
// 🔹 METRICS
//

function getDominanceRatio(probs) {
  if (!probs) return 0;
  const values = Object.values(probs).sort((a, b) => b - a);
  if (values.length < 2) return 0;
  return values[1] === 0 ? 0 : values[0] / values[1];
}

function getVariance(probs) {
  if (!probs) return 0;
  const values = Object.values(probs);
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length;
}

function getTopClass(probs) {
  if (!probs) return "unknown";
  return Object.entries(probs).sort((a, b) => b[1] - a[1])[0][0];
}

//
// 🔹 API CALL
//

async function analyzeRepo(repoLink) {
  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ repoLink })
    });

    return await res.json();
  } catch (err) {
    return { error: true };
  }
}

//
// 🔹 PROCESS REPO
//

async function processRepo(repoLink, expectedType) {
  console.log(`Testing: ${repoLink}`);

  const result = await analyzeRepo(repoLink);

  const probs = result.repoType?.probabilities || {};

  const predicted = getTopClass(probs);
  const confidence = result.repoType?.confidence || 0;
  const entropy = result.repoType?.entropy || 0;
  const separation = result.repoType?.separation || 0;

  const dominance = getDominanceRatio(probs);
  const variance = getVariance(probs);

  const correct = predicted === expectedType;

  return {
    repo_url: repoLink,
    expected_type: expectedType,
    predicted_type: predicted,
    confidence,

    prob_application: probs.application || 0,
    prob_library: probs.library || 0,
    prob_framework: probs.framework || 0,
    prob_cli: probs.cli || 0,
    prob_plugin: probs.plugin || 0,

    entropy,
    separation,
    dominance_ratio: dominance,
    variance,

    correct
  };
}

//
// 🔹 GLOBAL STATS
//

function computeStats(results) {
  const total = results.length;

  const accuracy =
    results.filter(r => r.correct).length / total;

  const avgEntropy =
    results.reduce((s, r) => s + r.entropy, 0) / total;

  const avgSeparation =
    results.reduce((s, r) => s + r.separation, 0) / total;

  const avgDominance =
    results.reduce((s, r) => s + r.dominance_ratio, 0) / total;

  const avgVariance =
    results.reduce((s, r) => s + r.variance, 0) / total;

  return {
    total,
    accuracy,
    avgEntropy,
    avgSeparation,
    avgDominance,
    avgVariance
  };
}

//
// 🔹 SAVE FILE
//

function saveResults(results) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const filePath = path.join("./tests", `results-${timestamp}.csv`);

  if (!fs.existsSync("./tests")) {
    fs.mkdirSync("./tests");
  }

  fs.writeFileSync(filePath, toCSV(results));

  console.log(`\nSaved: ${filePath}`);
}

//
// 🔹 RUN ALL
//

async function runGroup(repos, type, results) {
  console.log(`\n===== ${type.toUpperCase()} =====`);
  for (const repo of repos) {
    results.push(await processRepo(repo, type));
  }
}

async function run() {
  const results = [];

  await runGroup(LIBRARIES, "library", results);
  await runGroup(FRAMEWORKS, "framework", results);
  await runGroup(APPLICATIONS, "application", results);
  await runGroup(CLI_TOOLS, "cli", results);
  await runGroup(PLUGINS, "plugin", results);

  saveResults(results);

  const stats = computeStats(results);

  console.log("\n===== GLOBAL STATS =====");
  console.log(stats);
}

run();