import { build } from "esbuild";
import {
  copyFile,
  mkdir,
  readFile,
  readdir,
  writeFile,
} from "node:fs/promises";
import { createHash } from "node:crypto";

await mkdir(new URL("./dist/", import.meta.url), { recursive: true });
await build({
  entryPoints: ["src/main.ts"],
  bundle: true,
  format: "esm",
  target: "es2022",
  outfile: "dist/app.js",
  legalComments: "eof",
});
for (const file of ["index.html", "style.css"])
  await copyFile(file, `dist/${file}`);
const hash = createHash("sha256");
for (const file of [
  "package-lock.json",
  "build.mjs",
  "tsconfig.json",
  "index.html",
  "style.css",
  ...(await readdir("src")).sort().map((name) => `src/${name}`),
]) {
  hash.update(file);
  hash.update(await readFile(file));
}
await writeFile("dist/source.sha256", hash.digest("hex") + "\n");
