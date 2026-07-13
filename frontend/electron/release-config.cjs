const packageJson = require('../package.json');

const publisherNames = String(process.env.WINDOWS_PUBLISHER_NAME || '')
    .split(',')
    .map((value) => value.trim())
    .filter(Boolean);

if (!publisherNames.length) {
    throw new Error('WINDOWS_PUBLISHER_NAME is required for Windows release builds');
}
if (!process.env.CSC_LINK && !process.env.WIN_CSC_LINK) {
    throw new Error('CSC_LINK or WIN_CSC_LINK is required for Windows release builds');
}
if (!process.env.CSC_KEY_PASSWORD && !process.env.WIN_CSC_KEY_PASSWORD) {
    throw new Error('CSC_KEY_PASSWORD or WIN_CSC_KEY_PASSWORD is required for Windows release builds');
}

module.exports = {
    ...packageJson.build,
    forceCodeSigning: true,
    win: {
        ...packageJson.build.win,
        publisherName: publisherNames,
        verifyUpdateCodeSignature: true,
    },
};
