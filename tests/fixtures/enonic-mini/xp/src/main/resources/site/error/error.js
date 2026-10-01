const portal = require('/lib/xp/portal');

exports.handle404 = function () {
  return { status: 404, body: portal.getSite() };
};

exports.handleError = function () {
  return { status: 500 };
};
