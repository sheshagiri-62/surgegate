// Unit tests for pure logic (seat-map grouping, selection rules). next/jest compiles TS with SWC.
const nextJest = require("next/jest");
module.exports = nextJest({ dir: "./" })({ testEnvironment: "node", moduleNameMapper: { "^@/(.*)$": "<rootDir>/src/$1" } });
