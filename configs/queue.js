import { Queue } from "bullmq";
import IORedis from "ioredis";

/* ================= ENV CHECK ================= */
if (!process.env.REDIS_URL) {
throw new Error("REDIS_URL is not defined");
}

/* ================= REDIS CONNECTION ================= */
export const connection = new IORedis(process.env.REDIS_URL, {
maxRetriesPerRequest: null,
enableReadyCheck: false
});

/* ================= CONNECTION LOGS ================= */
connection.on("connect", () => {
console.log("Redis connected");
});

connection.on("ready", () => {
console.log("Redis ready");
});

connection.on("error", (err) => {
console.error("Redis error:", err);
});

connection.on("close", () => {
console.warn("Redis connection closed");
});

/* ================= QUEUE ================= */
export const analysisQueue = new Queue("analysisQueue", {
connection,
defaultJobOptions: {
attempts: 3,

    
    /* exponential retry: 2s → 4s → 8s */
    backoff: {
        type: "exponential",
        delay: 2000
    },

    removeOnComplete: true,
    removeOnFail: false
}
    

});
