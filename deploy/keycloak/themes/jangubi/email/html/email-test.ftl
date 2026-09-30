<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbTestTitle") eyebrow=msg("jbTestEyebrow")>
<@layout.p>${msg("jbTestIntro", realmName)}</@layout.p>
<@layout.signature/>
</@layout.emailLayout>
