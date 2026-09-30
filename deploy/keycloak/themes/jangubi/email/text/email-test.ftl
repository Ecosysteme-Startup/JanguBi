<#ftl output_format="plainText">
<#import "template.ftl" as layout>
<@layout.emailLayout title=msg("jbTestTitle") eyebrow=msg("jbTestEyebrow")>
${msg("jbTestIntro", realmName)}
</@layout.emailLayout>
