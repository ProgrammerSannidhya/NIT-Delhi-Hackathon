/**
 * INTEGRATION + UNIT TESTS — Analyze Routes & Services
 * POST /analyze · GET /analyze · GET /analyze/:id
 * startAnalysis · fetchAnalysisById · fetchUserAnalyses
 */

import { jest } from "@jest/globals";

// ─── Mock analyze layer ───────────────────────────────────────────────────────
const mockCreateAnalysis    = jest.fn();
const mockGetAnalysisById   = jest.fn();
const mockGetAnalysesByUser = jest.fn();
const mockFindRepoCache     = jest.fn();
const mockQueueAdd          = jest.fn();

jest.unstable_mockModule("../models/analyzeModel.js", () => ({
  createAnalysis:    mockCreateAnalysis,
  getAnalysisById:   mockGetAnalysisById,
  getAnalysesByUser: mockGetAnalysesByUser,
}));
jest.unstable_mockModule("../models/repoCacheModel.js", () => ({
  findRepoCache: mockFindRepoCache,
}));
jest.unstable_mockModule("../configs/queue.js", () => ({
  analysisQueue: { add: mockQueueAdd },
}));

// ─── Mock jwt ─────────────────────────────────────────────────────────────────
const mockJwtVerify = jest.fn();
jest.unstable_mockModule("jsonwebtoken", () => ({
  default: { verify: mockJwtVerify },
  verify:  mockJwtVerify,
}));

// ─── Infrastructure stubs ─────────────────────────────────────────────────────
jest.unstable_mockModule("../configs/env.js",      () => ({ validateEnv: jest.fn() }));
jest.unstable_mockModule("../configs/migrate.js",  () => ({ runMigrations: jest.fn().mockResolvedValue() }));
jest.unstable_mockModule("../configs/security.js", () => ({
  securityHeaders: (_, __, next) => next(),
  corsConfig:      (_, __, next) => next(),
  sanitizeInput:   (_, __, next) => next(),
}));
jest.unstable_mockModule("../configs/db.js",       () => ({ pool: { query: jest.fn() } }));
jest.unstable_mockModule("../middleware/rateLimiter.js", () => ({
  authLimiter:   (_, __, next) => next(),
  globalLimiter: (_, __, next) => next(),
}));
jest.unstable_mockModule("../middleware/requestLogger.js", () => ({
  requestLogger: (_, __, next) => next(),
}));
jest.unstable_mockModule("../utils/logger.js", () => ({
  default: { info: jest.fn(), error: jest.fn() },
}));
jest.unstable_mockModule("../services/authServices.js", () => ({
  registerUser: jest.fn(),
  loginUser:    jest.fn(),
}));
jest.unstable_mockModule("../utils/jwt.js", () => ({
  generateAccessToken:  jest.fn(() => "t"),
  generateRefreshToken: jest.fn(() => "r"),
  verifyToken:          jest.fn(),
}));
jest.unstable_mockModule("../models/tokenModel.js", () => ({
  createRefreshToken: jest.fn(),
  findRefreshToken:   jest.fn(),
  deleteRefreshToken: jest.fn(),
  rotateRefreshToken: jest.fn(),
}));
jest.unstable_mockModule("../services/userServices.js", () => ({
  createUserService:  jest.fn(),
  GetAllUsersService: jest.fn(),
  GetUserByIdService: jest.fn(),
  UpdateUserService:  jest.fn(),
  DeleteUserService:  jest.fn(),
}));

// ─── Boot app ─────────────────────────────────────────────────────────────────
const { default: app } = await import("../server.js");
const request = (await import("supertest")).default;

const USER       = { id: 7, role: "user" };
const AUTH       = "Bearer user.token";
const setUser    = () => mockJwtVerify.mockReturnValue(USER);

// ─── POST /analyze ────────────────────────────────────────────────────────────

describe("POST /analyze", () => {
  beforeEach(() => jest.clearAllMocks());

  it("202 — queues new analysis and returns analysisId", async () => {
    setUser();
    mockFindRepoCache.mockResolvedValue(null);
    mockCreateAnalysis.mockResolvedValue({ id: "uuid-123" });
    mockQueueAdd.mockResolvedValue();

    const res = await request(app)
      .post("/analyze")
      .set("Authorization", AUTH)
      .send({ repoLink: "https://github.com/user/repo" });

    expect(res.status).toBe(202);
    expect(res.body.analysisId).toBe("uuid-123");
    expect(mockQueueAdd).toHaveBeenCalledWith(
      "scan",
      expect.objectContaining({ analysisId: "uuid-123" })
    );
  });

  it("200 — returns cached result when repo was already analysed", async () => {
    setUser();
    mockFindRepoCache.mockResolvedValue({ result: { score: 99 } });

    const res = await request(app)
      .post("/analyze")
      .set("Authorization", AUTH)
      .send({ repoLink: "https://github.com/user/cached-repo" });

    expect(res.status).toBe(200);
    expect(res.body.message).toMatch(/cache/i);
    expect(res.body.data).toEqual({ score: 99 });
    expect(mockQueueAdd).not.toHaveBeenCalled();
  });

  it("400 — missing repoLink", async () => {
    setUser();

    const res = await request(app)
      .post("/analyze")
      .set("Authorization", AUTH)
      .send({});

    expect(res.status).toBe(400);
    expect(res.body.error).toMatch(/repoLink/i);
  });

  it("401 — unauthenticated", async () => {
    const res = await request(app)
      .post("/analyze")
      .send({ repoLink: "https://github.com/x/y" });
    expect(res.status).toBe(401);
  });

  it("normalizes repoLink — strips .git and trailing slash", async () => {
    setUser();
    mockFindRepoCache.mockResolvedValue(null);
    mockCreateAnalysis.mockResolvedValue({ id: "abc" });
    mockQueueAdd.mockResolvedValue();

    await request(app)
      .post("/analyze")
      .set("Authorization", AUTH)
      .send({ repoLink: "https://github.com/user/repo.git/" });

    expect(mockCreateAnalysis).toHaveBeenCalledWith(
      USER.id,
      "https://github.com/user/repo"
    );
  });
});

// ─── GET /analyze ─────────────────────────────────────────────────────────────

describe("GET /analyze", () => {
  beforeEach(() => jest.clearAllMocks());

  it("200 — returns all analyses for the authenticated user", async () => {
    setUser();
    mockGetAnalysesByUser.mockResolvedValue([{ id: "a1" }, { id: "a2" }]);

    const res = await request(app)
      .get("/analyze")
      .set("Authorization", AUTH);

    expect(res.status).toBe(200);
    expect(res.body).toHaveLength(2);
    expect(mockGetAnalysesByUser).toHaveBeenCalledWith(USER.id);
  });

  it("401 — unauthenticated", async () => {
    const res = await request(app).get("/analyze");
    expect(res.status).toBe(401);
  });
});

// ─── GET /analyze/:id ─────────────────────────────────────────────────────────

describe("GET /analyze/:id", () => {
  beforeEach(() => jest.clearAllMocks());

  it("200 — returns the analysis for given id", async () => {
    setUser();
    mockGetAnalysisById.mockResolvedValue({ id: "uuid-1", status: "done" });

    const res = await request(app)
      .get("/analyze/uuid-1")
      .set("Authorization", AUTH);

    expect(res.status).toBe(200);
    expect(res.body).toMatchObject({ id: "uuid-1" });
    expect(mockGetAnalysisById).toHaveBeenCalledWith("uuid-1");
  });

  it("401 — unauthenticated", async () => {
    const res = await request(app).get("/analyze/uuid-1");
    expect(res.status).toBe(401);
  });
});

// ─── UNIT: analyzeServices ────────────────────────────────────────────────────

const {
  startAnalysis,
  fetchAnalysisById,
  fetchUserAnalyses,
} = await import("../services/analyzeServices.js");

describe("startAnalysis()", () => {
  beforeEach(() => jest.clearAllMocks());

  it("returns cached result without creating a job", async () => {
    mockFindRepoCache.mockResolvedValue({ result: { ok: true } });

    const out = await startAnalysis(1, "https://github.com/x/y", "public");

    expect(out.cached).toBe(true);
    expect(out.result).toEqual({ ok: true });
    expect(mockCreateAnalysis).not.toHaveBeenCalled();
    expect(mockQueueAdd).not.toHaveBeenCalled();
  });

  it("creates a record and enqueues a job on cache miss", async () => {
    mockFindRepoCache.mockResolvedValue(null);
    mockCreateAnalysis.mockResolvedValue({ id: "job-1" });
    mockQueueAdd.mockResolvedValue();

    const out = await startAnalysis(1, "https://github.com/x/y.git", "private");

    expect(out.cached).toBe(false);
    expect(out.analysisId).toBe("job-1");
    expect(mockQueueAdd).toHaveBeenCalledWith(
      "scan",
      expect.objectContaining({ analysisId: "job-1", userType: "private" })
    );
  });

  it("normalizes URL before cache lookup", async () => {
    mockFindRepoCache.mockResolvedValue(null);
    mockCreateAnalysis.mockResolvedValue({ id: "x" });
    mockQueueAdd.mockResolvedValue();

    await startAnalysis(1, "HTTPS://GITHUB.COM/User/Repo.git/", "public");

    expect(mockFindRepoCache).toHaveBeenCalledWith(
      "https://github.com/user/repo"
    );
  });
});

describe("fetchAnalysisById()", () => {
  it("delegates to getAnalysisById", async () => {
    mockGetAnalysisById.mockResolvedValue({ id: "z" });
    const result = await fetchAnalysisById("z");
    expect(result).toEqual({ id: "z" });
    expect(mockGetAnalysisById).toHaveBeenCalledWith("z");
  });
});

describe("fetchUserAnalyses()", () => {
  it("delegates to getAnalysesByUser", async () => {
    mockGetAnalysesByUser.mockResolvedValue([{ id: "1" }]);
    const result = await fetchUserAnalyses(42);
    expect(result).toHaveLength(1);
    expect(mockGetAnalysesByUser).toHaveBeenCalledWith(42);
  });
});