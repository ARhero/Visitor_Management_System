// Does the web app need work before serving? Used by serve-public.bat so that a restart
// doesn't rebuild when nothing changed.
//   exit 0   up to date: web/dist is newer than every file that goes into the build
//   exit 10  rebuild needed (code changed, e.g. after git pull)
//   exit 20  packages changed too: npm install, then rebuild
// Any other exit (e.g. this script failing) should be treated as "rebuild".
import { existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const web = fileURLToPath(new URL("..", import.meta.url));
const mtime = (p) => (existsSync(p) ? statSync(p).mtimeMs : 0);

function newest(path) {
  if (!existsSync(path)) return 0;
  const s = statSync(path);
  if (!s.isDirectory()) return s.mtimeMs;
  let max = 0;
  for (const name of readdirSync(path)) max = Math.max(max, newest(join(path, name)));
  return max;
}

// npm writes node_modules/.package-lock.json on every install.
const installedAt = mtime(join(web, "node_modules", ".package-lock.json"));
if (!installedAt || mtime(join(web, "package-lock.json")) > installedAt) process.exit(20);

const builtAt = mtime(join(web, "dist", "index.html"));
if (!builtAt) process.exit(10);
const inputs = ["src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"];
for (const p of inputs) if (newest(join(web, p)) > builtAt) process.exit(10);
process.exit(0);
