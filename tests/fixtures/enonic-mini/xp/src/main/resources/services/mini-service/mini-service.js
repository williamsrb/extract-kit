const portal = require('/lib/xp/portal');

exports.get = function () {
  return { body: portal.getSite() };
};
