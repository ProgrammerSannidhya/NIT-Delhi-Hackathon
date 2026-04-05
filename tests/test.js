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
  "https://github.com/uuidjs/uuid",
  "https://github.com/expressjs/morgan",
  "https://github.com/validatorjs/validator.js",
  "https://github.com/ramda/ramda",
  "https://github.com/immerjs/immer",
  "https://github.com/ReactiveX/rxjs",
  "https://github.com/jashkenas/underscore",
  "https://github.com/moment/moment",
  "https://github.com/uuidjs/uuid"
];

const FRAMEWORKS = [
  "https://github.com/angular/angular",
  "https://github.com/nestjs/nest",
  "https://github.com/vercel/next.js",
  "https://github.com/vuejs/core",
  "https://github.com/facebook/react",
  "https://github.com/nuxt/nuxt",
  "https://github.com/sveltejs/kit",
  "https://github.com/emberjs/ember.js",
  "https://github.com/fastify/fastify",
  "https://github.com/koajs/koa",
  "https://github.com/remix-run/remix",
  "https://github.com/feathersjs/feathers"
];

const APPLICATIONS = [
  "https://github.com/TryGhost/Ghost",
  "https://github.com/gothinkster/react-redux-realworld-example-app",
  "https://github.com/supabase/supabase",
  "https://github.com/strapi/strapi",
  "https://github.com/mattermost/mattermost",
  "https://github.com/calcom/cal.com",
  "https://github.com/outline/outline",
  "https://github.com/ToolJet/ToolJet",
  "https://github.com/directus/directus",
  "https://github.com/appsmithorg/appsmith",
  "https://github.com/openblocks-dev/openblocks",
  "https://github.com/umami-software/umami"
];

const CLI_TOOLS = [
  "https://github.com/npm/cli",
  "https://github.com/yargs/yargs",
  "https://github.com/eslint/eslint",
  "https://github.com/prettier/prettier",
  "https://github.com/httpie/cli",
  "https://github.com/chalk/chalk",
  "https://github.com/tj/commander.js",
  "https://github.com/vercel/turbo",
  "https://github.com/nodemon/nodemon",
  "https://github.com/yeoman/yo",
  "https://github.com/sindresorhus/np",
  "https://github.com/open-cli-tools/concurrently"
];

const PLUGINS = [
  "https://github.com/jsx-eslint/eslint-plugin-react",
  "https://github.com/vitejs/vite-plugin-react",
  "https://github.com/typescript-eslint/typescript-eslint",
  "https://github.com/prettier/eslint-plugin-prettier",
  "https://github.com/remarkjs/remark",
  "https://github.com/rehypejs/rehype",
  "https://github.com/vitejs/vite-plugin-vue",
  "https://github.com/rollup/plugins",
  "https://github.com/webpack-contrib/mini-css-extract-plugin",
  "https://github.com/postcss/autoprefixer",
  "https://github.com/webpack-contrib/css-loader",
  "https://github.com/stylelint/stylelint"
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
  if (!probs || typeof probs !== "object") return 0;
  const values = Object.values(probs).map(v => Number(v) || 0).sort((a, b) => b - a);
  if (values.length < 2) return 0;
  return values[1] === 0 ? 0 : values[0] / values[1];
}

function getVariance(probs) {
  if (!probs || typeof probs !== "object") return 0;
  const values = Object.values(probs).map(v => Number(v) || 0);
  if (!values.length) return 0;
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  return values.reduce((sum, v) => sum + (v - mean) ** 2, 0) / values.length;
}

function getTopClass(probs) {
  if (!probs || typeof probs !== "object") return "unknown";

  const entries = Object.entries(probs).filter(
    ([, v]) => typeof v === "number" && Number.isFinite(v)
  );

  if (!entries.length) return "unknown";

  entries.sort((a, b) => b[1] - a[1]);
  return entries[0][0];
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

    const payload = await res.json().catch(() => ({}));

    if (!res.ok) {
      return { error: true, message: payload?.message || `HTTP ${res.status}` };
    }

    return payload;
  } catch (err) {
    return { error: true, message: err?.message || "fetch failed" };
  }
}

//
// 🔹 PROCESS REPO
//

async function processRepo(repoLink, expectedType) {
  console.log(`Testing: ${repoLink}`);

  const result = await analyzeRepo(repoLink);

  const probs = (
    result?.repoType?.probabilities &&
    typeof result.repoType.probabilities === "object" &&
    Object.keys(result.repoType.probabilities).length > 0
  )
    ? result.repoType.probabilities
    : {
        application: 0,
        library: 0,
        framework: 0,
        cli: 0,
        plugin: 0
      };

  const predicted = getTopClass(probs);
  const confidence = result?.repoType?.confidence || 0;
  const entropy = result?.repoType?.entropy || 0;
  const separation = result?.repoType?.separation || 0;

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

    correct,
    error: !!result?.error,
    error_message: result?.error ? (result?.message || "analysis error") : ""
  };
}

//
// 🔹 GLOBAL STATS
//

function computeStats(results) {
  const total = results.length || 1;

  const accuracy =
    results.filter(r => r.correct).length / total;

  const avgEntropy =
    results.reduce((s, r) => s + (Number(r.entropy) || 0), 0) / total;

  const avgSeparation =
    results.reduce((s, r) => s + (Number(r.separation) || 0), 0) / total;

  const avgDominance =
    results.reduce((s, r) => s + (Number(r.dominance_ratio) || 0), 0) / total;

  const avgVariance =
    results.reduce((s, r) => s + (Number(r.variance) || 0), 0) / total;

  return {
    total: results.length,
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
    fs.mkdirSync("./tests", { recursive: true });
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