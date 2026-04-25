import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

// ─── 1. Mock functions ────────────────────────────────────────────────────────
const mockCreate  = mock.fn();
const mockGetAll  = mock.fn();
const mockGetById = mock.fn();
const mockUpdate  = mock.fn();
const mockDelete  = mock.fn();

const mockJwtVerify = mock.fn();

// ─── 2. Register Mock Modules (Must happen before dynamic imports) ────────────
mock.module("../services/userServices.js", {
  namedExports: {
    createUserService:  mockCreate,
    GetAllUsersService: mockGetAll,
    GetUserByIdService: mockGetById,
    UpdateUserService:  mockUpdate,
    DeleteUserService:  mockDelete,
  }
});

mock.module("jsonwebtoken", {
  namedExports: { verify: mockJwtVerify },
  defaultExport: { verify: mockJwtVerify },
});

// Infrastructure stubs
mock.module("../configs/env.js",      { namedExports: { validateEnv: mock.fn() } });
mock.module("../configs/migrate.js",  { namedExports: { runMigrations: mock.fn(async () => {}) } });
mock.module("../configs/security.js", {
  namedExports: {
    securityHeaders: (_, __, next) => next(),
    corsConfig:      (_, __, next) => next(),
    sanitizeInput:   (_, __, next) => next(),
  }
});
mock.module("../configs/db.js", { namedExports: { pool: { query: mock.fn() } } });
mock.module("../middleware/rateLimiter.js", {
  namedExports: {
    authLimiter:   (_, __, next) => next(),
    globalLimiter: (_, __, next) => next(),
  }
});
mock.module("../middleware/requestLogger.js", { namedExports: { requestLogger: (_, __, next) => next() } });
mock.module("../utils/logger.js", { defaultExport: { info: mock.fn(), error: mock.fn() } });
mock.module("../services/authServices.js", { namedExports: { registerUser: mock.fn(), loginUser: mock.fn() } });
mock.module("../utils/jwt.js", {
  namedExports: {
    generateAccessToken:  mock.fn(() => "t"),
    generateRefreshToken: mock.fn(() => "r"),
    verifyToken:          mock.fn(),
  }
});
mock.module("../models/tokenModel.js", {
  namedExports: {
    createRefreshToken: mock.fn(),
    findRefreshToken:   mock.fn(),
    deleteRefreshToken: mock.fn(),
    rotateRefreshToken: mock.fn(),
  }
});
mock.module("../models/analyzeModel.js", {
  namedExports: { createAnalysis: mock.fn(), getAnalysisById: mock.fn(), getAnalysesByUser: mock.fn() }
});
mock.module("../models/repoCacheModel.js", { namedExports: { findRepoCache: mock.fn() } });
mock.module("../configs/queue.js", { namedExports: { analysisQueue: { add: mock.fn() } } });

// ─── 3. Dynamic Imports ───────────────────────────────────────────────────────
const { default: app } = await import("../server.js");
const { default: request } = await import("supertest");

// ─── Token helpers ────────────────────────────────────────────────────────────
const ADMIN   = { id: 99, role: "admin" };
const REGULAR = { id: 5,  role: "user"  };

const setUser = (payload) => {
  mockJwtVerify.mock.mockImplementationOnce(() => payload);
};

function clearAllMocks() {
  mockCreate.mock.resetCalls();
  mockGetAll.mock.resetCalls();
  mockGetById.mock.resetCalls();
  mockUpdate.mock.resetCalls();
  mockDelete.mock.resetCalls();
  mockJwtVerify.mock.resetCalls();
}

// ─── POST /users ──────────────────────────────────────────────────────────────

describe("POST /users", () => {
  beforeEach(() => clearAllMocks());

  it("201 — admin creates a user", async () => {
    setUser(ADMIN);
    mockCreate.mock.mockImplementationOnce(async () => ({ id: 10, username: "newuser" }));

    const res = await request(app)
      .post("/users")
      .set("Authorization", "Bearer admin.token")
      .send({ username: "newuser" });

    assert.strictEqual(res.status, 201);
    assert.strictEqual(res.body.data.username, "newuser");
  });

  it("403 — non-admin is forbidden", async () => {
    setUser(REGULAR);

    const res = await request(app)
      .post("/users")
      .set("Authorization", "Bearer user.token")
      .send({ username: "newuser" });
    assert.strictEqual(res.status, 403);
  });

  it("400 — duplicate username (pg error 23505)", async () => {
    setUser(ADMIN);
    const err = Object.assign(new Error("dup"), { code: "23505" });
    mockCreate.mock.mockImplementationOnce(async () => { throw err; });

    const res = await request(app)
      .post("/users")
      .set("Authorization", "Bearer admin.token")
      .send({ username: "taken" });

    assert.strictEqual(res.status, 400);
    assert.match(res.body.error, /already exists/i);
  });
});

// ─── GET /users ───────────────────────────────────────────────────────────────

describe("GET /users", () => {
  beforeEach(() => clearAllMocks());

  it("200 — admin gets list of users", async () => {
    setUser(ADMIN);
    mockGetAll.mock.mockImplementationOnce(async () => [{ id: 1 }, { id: 2 }]);

    const res = await request(app)
      .get("/users")
      .set("Authorization", "Bearer admin.token");

    assert.strictEqual(res.status, 200);
    assert.strictEqual(res.body.data.length, 2);
  });

  it("401 — no token", async () => {
    const res = await request(app).get("/users");
    assert.strictEqual(res.status, 401);
  });
});

// ─── GET /users/:id ───────────────────────────────────────────────────────────

describe("GET /users/:id", () => {
  beforeEach(() => clearAllMocks());

  it("200 — admin can fetch any user", async () => {
    setUser(ADMIN);
    mockGetById.mock.mockImplementationOnce(async () => ({ id: 5, username: "someone" }));

    const res = await request(app)
      .get("/users/5")
      .set("Authorization", "Bearer admin.token");

    assert.strictEqual(res.status, 200);
    assert.strictEqual(res.body.data.id, 5);
  });

  it("403 — user cannot fetch another user's record", async () => {
    setUser(REGULAR); // user.id is 5

    const res = await request(app)
      .get("/users/99")
      .set("Authorization", "Bearer user.token");
    assert.strictEqual(res.status, 403);
  });

  it("404 — user not found", async () => {
    setUser(ADMIN);
    mockGetById.mock.mockImplementationOnce(async () => null);

    const res = await request(app)
      .get("/users/999")
      .set("Authorization", "Bearer admin.token");
    assert.strictEqual(res.status, 404);
  });
});

// ─── PUT /users/:id ───────────────────────────────────────────────────────────

describe("PUT /users/:id", () => {
  beforeEach(() => clearAllMocks());

  it("200 — user updates their own record", async () => {
    setUser(REGULAR); // id: 5
    mockUpdate.mock.mockImplementationOnce(async () => ({ id: 5, username: "newname" }));

    const res = await request(app)
      .put("/users/5")
      .set("Authorization", "Bearer user.token")
      .send({ username: "newname" });
    assert.strictEqual(res.status, 200);
    assert.strictEqual(res.body.data.username, "newname");
  });

  it("403 — user cannot update another user", async () => {
    setUser(REGULAR);

    const res = await request(app)
      .put("/users/99")
      .set("Authorization", "Bearer user.token")
      .send({ username: "hack" });
    assert.strictEqual(res.status, 403);
  });
});

// ─── DELETE /users/:id ────────────────────────────────────────────────────────

describe("DELETE /users/:id", () => {
  beforeEach(() => clearAllMocks());

  it("200 — admin deletes a user", async () => {
    setUser(ADMIN);
    mockDelete.mock.mockImplementationOnce(async () => ({ id: 5, username: "gone" }));

    const res = await request(app)
      .delete("/users/5")
      .set("Authorization", "Bearer admin.token");

    assert.strictEqual(res.status, 200);
    assert.match(res.body.message, /deleted/i);
  });

  it("403 — non-admin is forbidden", async () => {
    setUser(REGULAR);

    const res = await request(app)
      .delete("/users/5")
      .set("Authorization", "Bearer user.token");
    assert.strictEqual(res.status, 403);
  });
});