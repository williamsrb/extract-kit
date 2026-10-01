const contentLib = require('/lib/xp/content');
const i18n = require('/lib/xp/i18n');
const thymeleaf = require('/lib/thymeleaf');

// contentLib.remove({ key: 'commented-out' });
exports.get = function (req) {
  const hits = contentLib.query({
    query: "type = 'com.example.mini:mini-article'",
    contentTypes: ['com.example.mini:mini-article'],
    count: 5,
  });
  const title = i18n.localize({ key: 'mini.title', locales: req.locales });
  const mode = app.config['miniMode'] || app.config.fallback;
  return { body: thymeleaf.render(resolve('mini-part.html'), { hits, title, mode }) };
};
