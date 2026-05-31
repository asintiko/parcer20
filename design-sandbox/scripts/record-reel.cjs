/**
 * Record /reel page into a polished MP4.
 * Pipeline:
 *   1. Launch headless Chromium at 1920x1080
 *   2. Open dev server with ?reel=1
 *   3. Sit through ~50s of scenes (7 × 6.8s)
 *   4. Save webm via Playwright `recordVideo`
 *   5. Convert webm to MP4 H.264 with ffmpeg (spawnSync, no shell)
 */

const { chromium } = require('playwright');
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const VIDEO_DIR = path.resolve(__dirname, '../public/reel');
const TMP_DIR = path.resolve(__dirname, '../.reel-tmp');
const FINAL_MP4 = path.resolve(VIDEO_DIR, 'design-evolution.mp4');
const URL = process.env.REEL_URL || 'http://127.0.0.1:5180/?reel=1';

// 7 scenes by 6.8s + 1.5s tail
const RECORD_MS = 7 * 6800 + 1500;

async function main() {
    if (!fs.existsSync(VIDEO_DIR)) fs.mkdirSync(VIDEO_DIR, { recursive: true });
    if (fs.existsSync(TMP_DIR)) fs.rmSync(TMP_DIR, { recursive: true, force: true });
    fs.mkdirSync(TMP_DIR, { recursive: true });

    const browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({
        viewport: { width: 1920, height: 1080 },
        deviceScaleFactor: 2,
        recordVideo: {
            dir: TMP_DIR,
            size: { width: 1920, height: 1080 },
        },
        colorScheme: 'light',
    });

    const page = await context.newPage();
    console.log('navigating ' + URL);
    await page.goto(URL, { waitUntil: 'networkidle' });

    await page.waitForSelector('.rl-root', { timeout: 10000 });
    console.log('recording ' + (RECORD_MS / 1000).toFixed(1) + 's');

    await page.waitForTimeout(RECORD_MS);

    await context.close();
    await browser.close();

    const webmFile = fs.readdirSync(TMP_DIR).find((f) => f.endsWith('.webm'));
    if (!webmFile) throw new Error('no webm produced');
    const webmPath = path.join(TMP_DIR, webmFile);
    console.log('webm: ' + webmPath);

    const ffmpegArgs = [
        '-y',
        '-i',
        webmPath,
        '-c:v',
        'libx264',
        '-preset',
        'slow',
        '-crf',
        '18',
        '-pix_fmt',
        'yuv420p',
        '-movflags',
        '+faststart',
        '-r',
        '30',
        FINAL_MP4,
    ];
    console.log('ffmpeg encoding...');
    const result = spawnSync('ffmpeg', ffmpegArgs, { stdio: 'inherit' });
    if (result.status !== 0) {
        throw new Error('ffmpeg failed with status ' + result.status);
    }

    fs.rmSync(TMP_DIR, { recursive: true, force: true });
    const stats = fs.statSync(FINAL_MP4);
    console.log('OK ' + FINAL_MP4 + ' (' + (stats.size / 1024 / 1024).toFixed(2) + ' MB)');
}

main().catch((err) => {
    console.error(err);
    process.exit(1);
});
