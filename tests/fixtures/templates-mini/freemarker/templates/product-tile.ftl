<#assign total = price * quantity>
<div class="tile">
  <#if price gt 150>
    <span class="premium">Premium</span>
  </#if>
  <#include "price-tag.ftl">
  ${total?string.currency}
</div>
