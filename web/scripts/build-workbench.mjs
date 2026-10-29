import { cp, mkdir, realpath } from "node:fs/promises";
import { dirname, resolve, relative, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";

// Preserve native modules and the import map; production uses these exact assets.
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = await realpath(resolve(webRoot, "../lsprepost_mcp/web/static"));
const output = resolve(process.argv[2] || resolve(webRoot, "dist"));
const within = (base, candidate) => {
  const value = relative(base, candidate);
  return value === "" || (!value.startsWith("..") && !isAbsolute(value));
};
if (within(source, output) || within(output, source)) {
  throw new Error("Build output must be separate from workbench source");
}
await mkdir(output, { recursive: true });
const destination = await realpath(output);
if (within(source, destination) || within(destination, source)) {
  throw new Error("Build output resolves into workbench source");
}
await cp(source, destination, { recursive: true });
console.log(`Workbench built at ${destination}`);
