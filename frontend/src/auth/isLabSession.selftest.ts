/**
 * Self-test for lab session identity.
 * Run: npx --yes tsx src/auth/isLabSession.selftest.ts  (from frontend/)
 */
import { isLabSession } from "./isLabSession";

if (isLabSession({ is_demo: true, demo_kind: "lab" }) !== true) {
  throw new Error("lab: is_demo + demo_kind lab should be true");
}

if (isLabSession({ is_demo: true, demo_kind: "sandbox" }) !== false) {
  throw new Error("sandbox: is_demo + demo_kind sandbox should be false");
}

if (isLabSession({ is_demo: true, demo_kind: "tour" }) !== false) {
  throw new Error("tour: is_demo + demo_kind tour should be false");
}

if (isLabSession({ is_demo: false, demo_kind: null }) !== false) {
  throw new Error("owner: is_demo false + null kind should be false");
}
if (isLabSession({ is_demo: undefined, demo_kind: "" }) !== false) {
  throw new Error("owner: undefined is_demo + empty kind should be false");
}

if (isLabSession(null) !== false) {
  throw new Error("null user should be false");
}
if (isLabSession(undefined) !== false) {
  throw new Error("undefined user should be false");
}

if (isLabSession({ is_demo: true }) !== false) {
  throw new Error("legacy is_demo without kind should be false");
}
if (isLabSession({ is_demo: true, demo_kind: null }) !== false) {
  throw new Error("legacy is_demo + null kind should be false");
}
if (isLabSession({ is_demo: true, demo_kind: "" }) !== false) {
  throw new Error("legacy is_demo + empty kind should be false");
}

if (isLabSession({ is_demo: false, demo_kind: "lab" }) !== false) {
  throw new Error("is_demo false with demo_kind lab should be false");
}

console.log("isLabSession.selftest: ok");
