import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

// ─── Mock auth services ───────────────────────────────────────────────────────
const mockRegisterUser = mock.fn();
const mockLoginUser    = mock.fn();
mock.module("../services/authServices.js", {
  namedExports: {
    registerUser: mockRegisterUser,
    loginUser:    mockLoginUser,
  },
});

// ─── Mock JWT utils ───────────────────────────────────────────────────────────
const mockGenerateAccessToken  = mock.fn(() => "mock.access.token");
const mockGenerateRefreshToken = mock.fn(() => "mock.refresh.token");
const mockVerifyToken          = mock.fn();
mock.module("../utils/jwt.js", {
  namedExports: {
    generateAccessToken:  mockGenerateAccessToken,
    generateRefreshToken: mockGenerateRefreshToken,
    verifyToken:          mockVerifyToken,
  },
});

// ─── Mock token model ─────────────────────────────────────────────────────────
const mockCreateRefreshToken = mock.fn();
const mockFindRefreshToken   = mock.fn();
const mockDeleteRefreshToken = mock.fn();
const mockRotateRefreshToken = mock.fn();
mock.module("../models/tokenModel.js", {
  namedExports: {
    createRefreshToken: mockCreateRefreshToken,
    findRefreshToken:   mockFindRefreshToken,
    deleteRefreshToken: mockDeleteRefreshToken,
    rotateRefreshToken: mockRotateRefreshToken,
  },
});

// ─── Mock jsonwebtoken (used by authMiddleware) ───────────────────────────────
const mockJwtVerify = mock.fn();
mock.module("jsonwebtoken", {
  namedExports: { verify: mockJwtVerify },
  defaultExport: { verify: mockJwtVerify },
});

// ─── Infrastructure stubs ─────────────────────────────────────────────────────
mock.module("../configs/env.js",      { namedExports: { validateEnv: mock.fn() } });
mock.module("../configs/migrate.js",  { namedExports: { runMigrations: mock.fn(async () => {}) } });
mock.module("../configs/security.js", {
  namedExports: {
    securityHeaders: (_, __, next) => next(),
    corsConfig:      (_, __, next) => next(),
    sanitizeInput:   (_, __, next) => next(),
  }
});
mock.module("../configs/db.js", {
  namedExports: { pool: { query: mock.fn() } }
});
mock.module("../middleware/rateLimiter.js", {
  namedExports: {
    authLimiter:   (_, __, next) => next(),
    globalLimiter: (_, __, next) => next(),
  }
});
mock.module("../middleware/requestLogger.js", {
  namedExports: { requestLogger: (_, __, next) => next() }
});
mock.module("../utils/logger.js", {
  defaultExport: { info: mock.fn(), error: mock.fn() }
});
mock.module("../services/userServices.js", {
  namedExports: {
    createUserService: mock.fn(),
    GetAllUsersService: mock.fn(),
    GetUserByIdService: mock.fn(),
    UpdateUserService: mock.fn(),
    DeleteUserService: mock.fn(),
  }
});
mock.module("../models/analyzeModel.js", {
  namedExports: {
    createAnalysis:    mock.fn(),
    getAnalysisById:   mock.fn(),
    getAnalysesByUser: mock.fn(),
  }
});
mock.module("../models/repoCacheModel.js", {
  namedExports: { findRepoCache: mock.fn() }
});
mock.module("../configs/queue.js", {
  namedExports: { analysisQueue: { add: mock.fn() } }
});

// ─── Boot app AFTER all mocks are in place ────────────────────────────────────
const { default: app } = await import("../server.js");
const { default: request } = await import("supertest");

// ─── Helpers ──────────────────────────────────────────────────────────────────
function clearAllMocks() {
  mockRegisterUser.mock.resetCalls();
  mockLoginUser.mock.resetCalls();
  mockGenerateAccessToken.mock.resetCalls();
  mockGenerateRefreshToken.mock.resetCalls();
  mockVerifyToken.mock.resetCalls();
  mockCreateRefreshToken.mock.resetCalls();
  mockFindRefreshToken.mock.resetCalls();
  mockDeleteRefreshToken.mock.resetCalls();
  mockRotateRefreshToken.mock.resetCalls();
  mockJwtVerify.mock.resetCalls();
}

// ─── POST /auth/register ──────────────────────────────────────────────────────

describe("POST /auth/register", () => {
  beforeEach(() => clearAllMocks());

  it("201 — creates a user and returns it", async () => {
    mockRegisterUser.mock.mockImplementationOnce(async () => ({ id: 1, username: "Alice" }));

    const res = await request(app)
      .post("/auth/register")
      .send({ username: "Alice", password: "Secure1password" });

    assert.strictEqual(res.status, 201);
    assert.strictEqual(res.body.data.username, "Alice");
  });

  it("400 — rejects a missing username", async () => {
    const res = await request(app)
      .post("/auth/register")
      .send({ password: "Secure1password" });
    assert.strictEqual(res.status, 400);
  });

  it("400 — rejects a password shorter than 4 chars", async () => {
    const res = await request(app)
      .post("/auth/register")
      .send({ username: "Alice", password: "ab" });
    assert.strictEqual(res.status, 400);
  });

  it("500 — propagates service errors", async () => {
    mockRegisterUser.mock.mockImplementationOnce(async () => { throw new Error("DB exploded"); });

    const res = await request(app)
      .post("/auth/register")
      .send({ username: "Alice", password: "Secure1password" });
    assert.strictEqual(res.status, 500);
  });
});

// ─── POST /auth/login ─────────────────────────────────────────────────────────

describe("POST /auth/login", () => {
  const FAKE_USER = { id: 1, username: "Alice", role: "user" };
  beforeEach(() => clearAllMocks());

  it("200 — returns access + refresh tokens on success", async () => {
    mockLoginUser.mock.mockImplementationOnce(async () => FAKE_USER);
    mockCreateRefreshToken.mock.mockImplementationOnce(async () => {});

    const res = await request(app)
      .post("/auth/login")
      .send({ username: "Alice", password: "Secure1password" });

    assert.strictEqual(res.status, 200);
    assert.ok(res.body.data.accessToken);
    assert.ok(res.body.data.refreshToken);
  });

  it("401 — invalid credentials", async () => {
    mockLoginUser.mock.mockImplementationOnce(async () => null);

    const res = await request(app)
      .post("/auth/login")
      .send({ username: "Alice", password: "wrongpass" });
    assert.strictEqual(res.status, 401);
  });
});

// ─── POST /auth/refresh ───────────────────────────────────────────────────────

describe("POST /auth/refresh", () => {
  beforeEach(() => clearAllMocks());

  it("200 — rotates tokens successfully", async () => {
    mockFindRefreshToken.mock.mockImplementationOnce(async () => ({ userId: 1 }));
    mockVerifyToken.mock.mockImplementationOnce(() => ({ id: 1, role: "user" }));
    mockRotateRefreshToken.mock.mockImplementationOnce(async () => {});

    const res = await request(app)
      .post("/auth/refresh")
      .send({ token: "valid.refresh.token" });

    assert.strictEqual(res.status, 200);
    assert.ok(res.body.data.accessToken);
    assert.ok(res.body.data.refreshToken);
  });

  it("403 — token not found in store", async () => {
    mockFindRefreshToken.mock.mockImplementationOnce(async () => null);

    const res = await request(app)
      .post("/auth/refresh")
      .send({ token: "unknown.token" });
    assert.strictEqual(res.status, 403);
  });
});

// ─── POST /auth/logout ────────────────────────────────────────────────────────

describe("POST /auth/logout", () => {
  beforeEach(() => clearAllMocks());

  it("200 — deletes token and confirms logout", async () => {
    mockDeleteRefreshToken.mock.mockImplementationOnce(async () => {});

    const res = await request(app)
      .post("/auth/logout")
      .send({ token: "some.refresh.token" });

    assert.strictEqual(res.status, 200);
    assert.match(res.body.message, /logged out/i);
  });
});

// ─── GET /auth/me ─────────────────────────────────────────────────────────────

describe("GET /auth/me", () => {
  beforeEach(() => clearAllMocks());

  it("200 — returns decoded user from token", async () => {
    const PAYLOAD = { id: 1, role: "user" };
    mockJwtVerify.mock.mockImplementationOnce(() => PAYLOAD);

    const res = await request(app)
      .get("/auth/me")
      .set("Authorization", "Bearer valid.token");

    assert.strictEqual(res.status, 200);
    assert.strictEqual(res.body.data.id, PAYLOAD.id);
  });

  it("401 — invalid / expired token", async () => {
    mockJwtVerify.mock.mockImplementationOnce(() => { throw new Error("jwt expired"); });

    const res = await request(app)
      .get("/auth/me")
      .set("Authorization", "Bearer bad.token");
    assert.strictEqual(res.status, 401);
  });
});