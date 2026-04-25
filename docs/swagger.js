// docs/swagger.js
// Mount this in server.js AFTER all existing route registrations:
//   import { swaggerRouter } from "./docs/swagger.js";
//   app.use(swaggerRouter);

import { createRequire } from "module";
import { fileURLToPath } from "url";
import path from "path";
import express from "express";

const require = createRequire(import.meta.url);
const swaggerUi = require("swagger-ui-express");

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Load the spec at startup so it is always current
const swaggerDocument = JSON.parse(
  (await import("fs")).readFileSync(
    path.join(__dirname, "swagger.json"),
    "utf-8"
  )
);

export const swaggerRouter = express.Router();

swaggerRouter.use(
  "/docs",
  swaggerUi.serve,
  swaggerUi.setup(swaggerDocument, {
    customSiteTitle: "CodePlus API Docs",
    swaggerOptions: {
      persistAuthorization: true,
    },
  })
);