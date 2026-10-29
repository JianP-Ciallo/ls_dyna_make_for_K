import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const generatedRoot = fileURLToPath(new URL("../var/tmp/", import.meta.url));
export function generatedPath(...parts) {
  return resolve(generatedRoot, ...parts);
}
