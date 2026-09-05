import { transformSync } from "@babel/core";
import presetReact from "@babel/preset-react";
import { cp, mkdir, readFile, readdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";

const source = path.resolve("public/static/hifi");
const output = path.resolve("public/build/hifi");
const transform = (code, filename) =>
    transformSync(code, {
        filename,
        presets: [[presetReact, { runtime: "classic" }]],
        comments: false,
        compact: true,
        minified: true,
        sourceMaps: false,
    })?.code ?? "";

await rm(output, { recursive: true, force: true });
await mkdir(path.join(output, "vendor"), { recursive: true });

for (const filename of await readdir(source)) {
    if (!filename.endsWith(".jsx")) continue;
    const code = await readFile(path.join(source, filename), "utf8");
    await writeFile(
        path.join(output, filename.replace(/\.jsx$/, ".js")),
        transform(code, filename),
    );
}

await cp(
    "node_modules/react/umd/react.production.min.js",
    path.join(output, "vendor/react.js"),
);
await cp(
    "node_modules/react-dom/umd/react-dom.production.min.js",
    path.join(output, "vendor/react-dom.js"),
);

let html = await readFile(path.join(source, "index.html"), "utf8");
html = html
    .replace(
        /<script\b[^>]*src="https:\/\/unpkg\.com\/react@[^>]*><\/script>/,
        '<script src="/build/hifi/vendor/react.js"></script>',
    )
    .replace(
        /<script\b[^>]*src="https:\/\/unpkg\.com\/react-dom@[^>]*><\/script>/,
        '<script src="/build/hifi/vendor/react-dom.js"></script>',
    )
    .replace(
        /<script\b[^>]*src="https:\/\/unpkg\.com\/@babel\/standalone@[^>]*><\/script>\s*/,
        "",
    )
    .replace(
        /<script\b[^>]*type="text\/babel"[^>]*src="\/static\/hifi\/([^"]+)\.jsx"[^>]*><\/script>/g,
        '<script src="/build/hifi/$1.js"></script>',
    );

html = html.replace(
    /<script type="text\/babel">([\s\S]*?)<\/script>/,
    (_, code) => `<script>${transform(code, "inline-app.jsx")}</script>`,
);
await writeFile(path.join(output, "index.html"), html);
