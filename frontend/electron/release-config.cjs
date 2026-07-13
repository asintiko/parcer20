const packageJson = require('../package.json');

module.exports = {
    ...packageJson.build,
    forceCodeSigning: false,
    win: {
        ...packageJson.build.win,
        verifyUpdateCodeSignature: false,
    },
};
