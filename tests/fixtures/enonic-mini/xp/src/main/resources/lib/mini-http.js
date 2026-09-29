const HttpClient = require('/lib/http-client');

exports.get = function () {
  return HttpClient.request({
    url: 'https://api.example.test/v1',
    method: 'GET',
  });
};
