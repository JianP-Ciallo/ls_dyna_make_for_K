const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticRoot = path.resolve(__dirname, "../../lsprepost_mcp/web/static");
function prepareWorkbenchSource(source, context) {
  for (const [name, exports] of [
    ["persistence", ["writeLatestProjectId", "writeSessionDraft", "clearRecovery", "safeStorageWrite"]],
    ["http", ["fetchJson"]],
    ["autosave", ["saveCurrentDraft"]],
  ]) {
    const filename = path.join(staticRoot, `refined_blast_${name}.js`);
    const code = fs.readFileSync(filename, "utf8")
      .replace(/^import .*;\r?$/gm, "")
      .replace(/export (async )?function /g, "$1function ");
    const values = new vm.Script(`(function () { ${code}\nreturn { ${exports.join(", ")} }; })()`, { filename }).runInContext(context);
    Object.assign(context, values);
  }
  return source.replace(/^import .*from "\.\/refined_blast_(persistence|http|autosave)\.js";\r?$/gm, "");
}
module.exports = { prepareWorkbenchSource };
