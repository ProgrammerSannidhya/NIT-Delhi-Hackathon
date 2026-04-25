/**
 * UNIT TESTS — Auth Services
 * registerUser · loginUser
 *
 * Uses jest.unstable_mockModule() — the correct ESM Jest pattern.
 * Run: node --experimental-vm-modules node_modules/.bin/jest tests/auth.unit.test.js
 */

import { jest } from "@jest/globals";

// ─── Mock dependencies BEFORE any import of the SUT ──────────────────────────

const mockCreateUser         = jest.fn();
const mockFindUserByUsername = jest.fn();
const mockIncrementFailed    = jest.fn();
const mockResetFailed        = jest.fn();
const mockLockUser           = jest.fn();

jest.unstable_mockModule("../models/userModel.js", () => ({
  createUser:              mockCreateUser,
  findUserByUsername:      mockFindUserByUsername,
  incrementFailedAttempts: mockIncrementFailed,
  resetFailedAttempts:     mockResetFailed,
  lockUser:                mockLockUser,
}));

const mockBcryptHash    = jest.fn();
const mockBcryptCompare = jest.fn();

jest.unstable_mockModule("bcrypt", () => ({
  default: {
    hash:    mockBcryptHash,
    compare: mockBcryptCompare,
  },
  hash:    mockBcryptHash,
  compare: mockBcryptCompare,
}));

// ─── Import SUT AFTER mocks are registered ────────────────────────────────────
const { registerUser, loginUser } = await import("../services/authServices.js");

// ─── REGISTER ─────────────────────────────────────────────────────────────────

describe("registerUser()", () => {
  beforeEach(() => jest.clearAllMocks());

  it("hashes the password and calls createUser on valid input", async () => {
    mockBcryptHash.mockResolvedValue("hashed_pw");
    mockCreateUser.mockResolvedValue({ id: 1, username: "Alice" });

    const result = await registerUser("Alice", "Secure1password");

    expect(mockBcryptHash).toHaveBeenCalledWith("Secure1password", 10);
    expect(mockCreateUser).toHaveBeenCalledWith({
      username: "Alice",
      password: "hashed_pw",
    });
    expect(result).toEqual({ id: 1, username: "Alice" });
  });

  it("rejects passwords shorter than 8 chars", async () => {
    await expect(registerUser("Alice", "Ab1")).rejects.toThrow(
      "Password must be 8+ chars"
    );
    expect(mockBcryptHash).not.toHaveBeenCalled();
  });

  it("rejects passwords without an uppercase letter", async () => {
    await expect(registerUser("Alice", "alllower1")).rejects.toThrow();
  });

  it("rejects passwords without a number", async () => {
    await expect(registerUser("Alice", "NoNumbers!")).rejects.toThrow();
  });

  it("rejects non-string passwords", async () => {
    await expect(registerUser("Alice", 12345678)).rejects.toThrow();
  });
});

// ─── LOGIN ────────────────────────────────────────────────────────────────────

describe("loginUser()", () => {
  const fakeUser = {
    id: 1,
    username: "Alice",
    password: "hashed_pw",
    lock_until: null,
    failed_attempts: 0,
  };

  beforeEach(() => jest.clearAllMocks());

  it("returns null when user is not found", async () => {
    mockFindUserByUsername.mockResolvedValue(null);
    const result = await loginUser("nobody", "pass");
    expect(result).toBeNull();
  });

  it("returns null and increments failed attempts on wrong password", async () => {
    mockFindUserByUsername.mockResolvedValue(fakeUser);
    mockBcryptCompare.mockResolvedValue(false);

    const result = await loginUser("Alice", "wrongpass");

    expect(result).toBeNull();
    expect(mockIncrementFailed).toHaveBeenCalledWith(1);
    expect(mockResetFailed).not.toHaveBeenCalled();
  });

  it("locks account after MAX_ATTEMPTS (5) failed logins", async () => {
    const almostLocked = { ...fakeUser, failed_attempts: 4 };
    mockFindUserByUsername.mockResolvedValue(almostLocked);
    mockBcryptCompare.mockResolvedValue(false);

    await loginUser("Alice", "wrong");

    expect(mockLockUser).toHaveBeenCalledWith(1, expect.any(Date));
  });

  it("resets failed_attempts and returns user on correct password", async () => {
    mockFindUserByUsername.mockResolvedValue(fakeUser);
    mockBcryptCompare.mockResolvedValue(true);

    const result = await loginUser("Alice", "Secure1password");

    expect(result).toEqual(fakeUser);
    expect(mockResetFailed).toHaveBeenCalledWith(1);
    expect(mockIncrementFailed).not.toHaveBeenCalled();
  });

  it("throws when account is locked", async () => {
    const lockedUser = {
      ...fakeUser,
      lock_until: new Date(Date.now() + 60_000).toISOString(),
    };
    mockFindUserByUsername.mockResolvedValue(lockedUser);

    await expect(loginUser("Alice", "Secure1password")).rejects.toThrow(
      "Account locked"
    );
  });

  it("allows login when lock_until is in the past", async () => {
    const expiredLock = {
      ...fakeUser,
      lock_until: new Date(Date.now() - 1000).toISOString(),
    };
    mockFindUserByUsername.mockResolvedValue(expiredLock);
    mockBcryptCompare.mockResolvedValue(true);

    const result = await loginUser("Alice", "Secure1password");
    expect(result).toEqual(expiredLock);
  });
});