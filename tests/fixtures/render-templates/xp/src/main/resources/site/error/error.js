const Io = require('/lib/xp/io');

exports.handleError = function (err) {
  const stream = Io.getResource(resolve('errorStatic.html')).getStream();
  return { status: 500, body: Io.readText(stream) };
};
