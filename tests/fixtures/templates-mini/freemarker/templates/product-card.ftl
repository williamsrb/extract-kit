<#-- Product card -->
<#import "price-tag.ftl" as pt>
<#macro card title price=0>
<div class="card">
  <h3>${title}</h3>
  <#if price gt 100>
    <span class="premium">Premium</span>
  </#if>
  <#if products?size gt 0>
    <#list products as product>
      <li>${product.name}</li>
    </#list>
  </#if>
  <@pt.tag value=price />
  <@spring.message "card.buy" />
</div>
</#macro>
