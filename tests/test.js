import fs from "fs";
import path from "path";

const API_URL = "http://localhost:3000/analyze";

//
// 🔹 REPO GROUPS (clean labels)
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
  "https://github.com/facebook/react"
];

const FRAMEWORKS = [
  "https://github.com/angular/angular",
  "https://github.com/nestjs/nest",
  "https://github.com/vercel/next.js",
  "https://github.com/vuejs/core",
  "https://github.com/nuxt/nuxt",
  "https://github.com/sveltejs/kit",
  "https://github.com/emberjs/ember.js",
  "https://github.com/remix-run/remix"
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
// 🔹 CSV
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

function getTop2(probs) {
  return Object.entries(probs || {})
    .filter(([_, v]) => typeof v === "number")
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2);
}

function getTopClass(probs) {
  return getTop2(probs)[0]?.[0] || "unknown";
}

function getGap(probs) {
  const [a, b] = getTop2(probs);
  return a && b ? a[1] - b[1] : 0;
}

//
// 🔹 API CALL (FIXED: includes userType)
//

async function analyzeRepo(repoLink, expectedType) {
  try {
    const res = await fetch(API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repoLink,
        userType: expectedType   // 🔥 critical fix
      })
    });

    const json = await res.json().catch(() => ({}));

    if (!res.ok) {
      return { error: true, message: json?.message || "HTTP error" };
    }

    return json;

  } catch (err) {
    return { error: true, message: err.message };
  }
}

//
// 🔹 PROCESS
//

async function processRepo(repoLink, expectedType) {
  console.log("Testing:", repoLink);

  const result = await analyzeRepo(repoLink, expectedType);

  const probs = result?.repoType?.probabilities || {
    application: 0,
    library: 0,
    framework: 0,
    cli: 0,
    plugin: 0
  };

  const predicted = getTopClass(probs);
  const gap = getGap(probs);

  return {
    repo_url: repoLink,
    expected_type: expectedType,
    predicted_type: predicted,
    confidence: result?.repoType?.confidence || 0,
    gap,

    prob_application: probs.application,
    prob_library: probs.library,
    prob_framework: probs.framework,
    prob_cli: probs.cli,
    prob_plugin: probs.plugin,

    correct: predicted === expectedType,
    top2: JSON.stringify(getTop2(probs)),
    error: !!result?.error,
    error_message: result?.error ? result.message : ""
  };
}

//
// 🔹 RUNNER
//

async function runGroup(repos, type, results) {
  console.log(`\n=== ${type.toUpperCase()} ===`);

  for (const repo of repos) {
    const r = await processRepo(repo, type);
    results.push(r);
  }
}

async function run() {
  const results = [];

  await runGroup(LIBRARIES, "library", results);
  await runGroup(FRAMEWORKS, "framework", results);
  await runGroup(APPLICATIONS, "application", results);
  await runGroup(CLI_TOOLS, "cli", results);
  await runGroup(PLUGINS, "plugin", results);

  const file = `./tests/results-${Date.now()}.csv`;

  if (!fs.existsSync("./tests")) {
    fs.mkdirSync("./tests", { recursive: true });
  }

  fs.writeFileSync(file, toCSV(results));

  console.log("\nSaved:", file);

  const accuracy =
    results.filter(r => r.correct).length / results.length;

  console.log("\nAccuracy:", accuracy.toFixed(3));
}

run();