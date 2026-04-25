/**
 * UNIT TESTS — Middleware
 * authMiddleware · roleMiddleware · ownershipMiddleware
 * userValidation · validate (auth input)
 *
 * Pure Jest ESM — no HTTP server, no DB.
 * Run: node --experimental-vm-modules node_modules/.bin/jest tests/middleware.unit.test.js
 */

import { jest } from "@jest/globals";

// ─── Helpers ──────────────────────────────────────────────────────────────────

const mkCtx = (overrides = {}) => {
  const res = {
    status: jest.fn().mockReturnThis(),
    json:   jest.fn().mockReturnThis(),
  };
  const req = { headers: {}, params: {}, body: {}, user: null, ...overrides };
  const next = jest.fn();
  return { req, res, next };
};

// ─── authMiddleware ───────────────────────────────────────────────────────────

const mockJwtVerify = jest.fn();

jest.unstable_mockModule("jsonwebtoken", () => ({
  default: { verify: mockJwtVerify },
  verify:  mockJwtVerify,
}));

const { protect } = await import("../middleware/authMiddleware.js");

describe("protect middleware", () => {
  const PAYLOAD = { id: 42, role: "user" };

  beforeEach(() => jest.clearAllMocks());

  it("calls next() and attaches decoded user when token is valid", () => {
    mockJwtVerify.mockReturnValue(PAYLOAD);
    const { req, res, next } = mkCtx({
      headers: { authorization: "Bearer valid.token.here" },
    });

    protect(req, res, next);

    expect(next).toHaveBeenCalled();
    expect(req.user).toEqual(PAYLOAD);
    expect(res.status).not.toHaveBeenCalled();
  });

  it("returns 401 when Authorization header is missing", () => {
    const { req, res, next } = mkCtx();
    protect(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
    expect(next).not.toHaveBeenCalled();
  });

  it("returns 401 when header does not start with 'Bearer '", () => {
    const { req, res, next } = mkCtx({
      headers: { authorization: "Basic dXNlcjpwYXNz" },
    });
    protect(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("returns 401 when jwt.verify throws (expired / invalid token)", () => {
    mockJwtVerify.mockImplementation(() => { throw new Error("jwt expired"); });
    const { req, res, next } = mkCtx({
      headers: { authorization: "Bearer bad.token" },
    });

    protect(req, res, next);

    expect(res.status).toHaveBeenCalledWith(401);
    expect(next).not.toHaveBeenCalled();
  });
});

// ─── roleMiddleware ───────────────────────────────────────────────────────────

const { allowRoles } = await import("../middleware/roleMiddleware.js");

describe("allowRoles middleware", () => {
  it("calls next() when user role is in allowed list", () => {
    const { req, res, next } = mkCtx({ user: { id: 1, role: "admin" } });
    allowRoles("admin", "moderator")(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it("returns 403 when user role is not in allowed list", () => {
    const { req, res, next } = mkCtx({ user: { id: 1, role: "user" } });
    allowRoles("admin")(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it("returns 403 when req.user is absent", () => {
    const { req, res, next } = mkCtx({ user: null });
    allowRoles("admin")(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
  });

  it("supports multiple allowed roles", () => {
    const { req, res, next } = mkCtx({ user: { role: "moderator" } });
    allowRoles("admin", "moderator", "editor")(req, res, next);
    expect(next).toHaveBeenCalled();
  });
});

// ─── ownershipMiddleware ──────────────────────────────────────────────────────

const { allowSelfOrAdmin } = await import("../middleware/ownershipMiddleware.js");

describe("allowSelfOrAdmin middleware", () => {
  it("calls next() for admin regardless of param id", () => {
    const { req, res, next } = mkCtx({
      user:   { id: 99, role: "admin" },
      params: { id: "1" },
    });
    allowSelfOrAdmin("id")(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it("calls next() when user accesses their own resource", () => {
    const { req, res, next } = mkCtx({
      user:   { id: 5, role: "user" },
      params: { id: "5" },
    });
    allowSelfOrAdmin("id")(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it("returns 403 when non-admin accesses another user's resource", () => {
    const { req, res, next } = mkCtx({
      user:   { id: 5, role: "user" },
      params: { id: "99" },
    });
    allowSelfOrAdmin("id")(req, res, next);
    expect(res.status).toHaveBeenCalledWith(403);
    expect(next).not.toHaveBeenCalled();
  });

  it("returns 401 when req.user is absent", () => {
    const { req, res, next } = mkCtx({ user: null, params: { id: "5" } });
    allowSelfOrAdmin("id")(req, res, next);
    expect(res.status).toHaveBeenCalledWith(401);
  });

  it("uses a custom paramKey", () => {
    const { req, res, next } = mkCtx({
      user:   { id: 7, role: "user" },
      params: { userId: "7" },
    });
    allowSelfOrAdmin("userId")(req, res, next);
    expect(next).toHaveBeenCalled();
  });
});

// ─── userValidation ───────────────────────────────────────────────────────────

const {
  validateUserCreate,
  validateUserUpdate,
  validateUserId,
} = await import("../middleware/userValidation.js");

const userValidationCases = [
  ["validateUserCreate", validateUserCreate],
  ["validateUserUpdate", validateUserUpdate],
];

for (const [label, mw] of userValidationCases) {
  describe(label, () => {
    it("calls next() on valid username", () => {
      const { req, res, next } = mkCtx({ body: { username: "validuser" } });
      mw(req, res, next);
      expect(next).toHaveBeenCalled();
    });

    it("returns 400 when username is missing", () => {
      const { req, res, next } = mkCtx({ body: {} });
      mw(req, res, next);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when username is not a string", () => {
      const { req, res, next } = mkCtx({ body: { username: 123 } });
      mw(req, res, next);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when username is too short (< 3 chars)", () => {
      const { req, res, next } = mkCtx({ body: { username: "ab" } });
      mw(req, res, next);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("returns 400 when username is too long (> 30 chars)", () => {
      const { req, res, next } = mkCtx({ body: { username: "a".repeat(31) } });
      mw(req, res, next);
      expect(res.status).toHaveBeenCalledWith(400);
    });

    it("accepts username at exact boundary lengths (3 and 30)", () => {
      for (const len of [3, 30]) {
        const { req, res, next } = mkCtx({ body: { username: "x".repeat(len) } });
        mw(req, res, next);
        expect(next).toHaveBeenCalled();
      }
    });
  });
}

describe("validateUserId", () => {
  it("calls next() for a numeric string id", () => {
    const { req, res, next } = mkCtx({ params: { id: "42" } });
    validateUserId(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it("returns 400 for a non-numeric id", () => {
    const { req, res, next } = mkCtx({ params: { id: "abc" } });
    validateUserId(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when id is missing", () => {
    const { req, res, next } = mkCtx({ params: {} });
    validateUserId(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });
});

// ─── validateAuth ─────────────────────────────────────────────────────────────

const { validateAuth } = await import("../middleware/validate.js");

describe("validateAuth middleware", () => {
  it("calls next() on valid username + password", () => {
    const { req, res, next } = mkCtx({
      body: { username: "Alice", password: "secret99" },
    });
    validateAuth(req, res, next);
    expect(next).toHaveBeenCalled();
  });

  it("returns 400 when username is missing", () => {
    const { req, res, next } = mkCtx({ body: { password: "secret99" } });
    validateAuth(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when username is not a string", () => {
    const { req, res, next } = mkCtx({ body: { username: 42, password: "secret99" } });
    validateAuth(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when password is shorter than 4 chars", () => {
    const { req, res, next } = mkCtx({ body: { username: "Alice", password: "ab" } });
    validateAuth(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });

  it("returns 400 when password is missing", () => {
    const { req, res, next } = mkCtx({ body: { username: "Alice" } });
    validateAuth(req, res, next);
    expect(res.status).toHaveBeenCalledWith(400);
  });
});