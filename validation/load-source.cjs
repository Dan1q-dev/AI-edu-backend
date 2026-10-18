const fs = require('node:fs'), path = require('node:path'), Module = require('node:module');
const root = path.resolve(__dirname, '../services/ai-tutor');
const ts = require(path.join(root, 'node_modules/typescript'));
const original = Module._resolveFilename;
Module._resolveFilename = function(request, parent, ...rest) {
  return original.call(this, request.startsWith('@/') ? path.join(root, request.slice(2)) : request, parent, ...rest);
};
require.extensions['.ts'] = function(mod, file) {
  mod._compile(ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
    target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, esModuleInterop: true,
  } }).outputText, file);
};
module.exports = { root, load: name => require(path.join(root, name)), dependency: name => require(path.join(root, 'node_modules', name)) };
