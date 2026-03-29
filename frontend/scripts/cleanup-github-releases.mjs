#!/usr/bin/env node

const owner = (process.env.UPDATER_GH_OWNER || "asintiko").trim();
const repo = (process.env.UPDATER_GH_REPO || "parcer20-updates").trim();
const token = (process.env.GH_TOKEN || process.env.GITHUB_TOKEN || "").trim();
const keepReleasesRaw = process.env.UPDATER_KEEP_RELEASES || "1";
const keepReleases = Number.parseInt(keepReleasesRaw, 10);

if (!token) {
    console.error("Missing GH_TOKEN (or GITHUB_TOKEN).");
    process.exit(1);
}

if (!Number.isInteger(keepReleases) || keepReleases < 1) {
    console.error(`Invalid UPDATER_KEEP_RELEASES value: ${keepReleasesRaw}`);
    process.exit(1);
}

async function ghRequest(path, options = {}) {
    const url = `https://api.github.com${path}`;
    const response = await fetch(url, {
        ...options,
        headers: {
            Accept: "application/vnd.github+json",
            Authorization: `Bearer ${token}`,
            "X-GitHub-Api-Version": "2022-11-28",
            ...(options.headers || {}),
        },
    });

    if (response.status === 204) {
        return null;
    }

    if (!response.ok) {
        const body = await response.text();
        throw new Error(`${response.status} ${response.statusText}: ${body}`);
    }

    return response.json();
}

function releaseDate(release) {
    return new Date(release.published_at || release.created_at || 0).getTime();
}

async function deleteTagRef(tagName) {
    const encodedTag = encodeURIComponent(tagName);
    try {
        await ghRequest(`/repos/${owner}/${repo}/git/refs/tags/${encodedTag}`, {
            method: "DELETE",
        });
        console.log(`Deleted tag: ${tagName}`);
    } catch (error) {
        const message = String(error?.message || error);
        if (message.includes("404")) {
            console.log(`Tag already removed: ${tagName}`);
            return;
        }
        throw error;
    }
}

async function main() {
    console.log(`Loading releases from ${owner}/${repo} ...`);
    const releases = await ghRequest(`/repos/${owner}/${repo}/releases?per_page=100`);

    if (!Array.isArray(releases) || releases.length <= keepReleases) {
        console.log("Nothing to cleanup.");
        return;
    }

    const sorted = releases.slice().sort((a, b) => releaseDate(b) - releaseDate(a));
    const toKeep = sorted.slice(0, keepReleases);
    const toDelete = sorted.slice(keepReleases);

    console.log(`Keeping ${toKeep.length} release(s), removing ${toDelete.length} old release(s).`);
    for (const release of toDelete) {
        const releaseLabel = `${release.tag_name || "no-tag"} (id=${release.id})`;
        await ghRequest(`/repos/${owner}/${repo}/releases/${release.id}`, { method: "DELETE" });
        console.log(`Deleted release: ${releaseLabel}`);
        if (release.tag_name) {
            await deleteTagRef(release.tag_name);
        }
    }
}

main().catch((error) => {
    console.error(`Release cleanup failed: ${error?.message || error}`);
    process.exit(1);
});
