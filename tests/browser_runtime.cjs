// Optional browser-test dependency: npm install --no-save playwright
const path = require('path');
const os = require('os');
if (process.env.ORR_PLAYWRIGHT_MODULE) {
  module.exports = require(process.env.ORR_PLAYWRIGHT_MODULE);
} else {
  try {
    module.exports = require('playwright');
  } catch (error) {
    if (error.code !== 'MODULE_NOT_FOUND') throw error;
    module.exports = require(path.join(os.homedir(), '.cache', 'codex-runtimes',
      'codex-primary-runtime', 'dependencies', 'node', 'node_modules', 'playwright'));
  }
}
