$(function () {
  $('#buy').on('click', function () {
    if (parseFloat($('#price').val()) > 100) {
      $('#premium').show();
    }
    if ($('#items').children().length > 0) {
      $('#items').show();
    }
  });
});
