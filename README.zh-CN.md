# ClaimDocs - 医疗账单文档演示

[在线演示](https://praveen-claimdocs.streamlit.app/) · [完整英文说明](README.md)

将虚构的医疗账单文本提取为可检查、修改和导出的结构化记录。当前界面支持文本或扫描 PDF、TXT、PNG、JPEG 和 TIFF。英文印刷文字 OCR 在应用服务器上使用 Tesseract 运行，无需额外 API 密钥。文件上限为 5 MB，PDF/TIFF 最多 10 页，上传图片每页最多 2000 万像素。OCR 可能误读姓名、代码和金额，导出前必须核对原始文件。

流程：选择示例或上传文件，读取文本，通过 Groq 提取字段，执行结构及金额检查，人工核对后导出 JSON/CSV。默认模型为 `openai/gpt-oss-20b`，可配置；不要将 Groq 与 xAI Grok 混淆。

该演示没有独立的字段准确率基准。上游 py-idp 的收据/发票分数不是 ClaimDocs 的测试结果。它不提交真实保险索赔，也未证明真实业务的节省时间或生产并发能力。仅使用虚构数据。

本项目基于 [rollroyces/py-idp](https://github.com/rollroyces/py-idp)。保留上游作者署名、Git 历史和 LICENSE、LICENSE-AGPL、LICENSE-COMMERCIAL。安装、配置、贡献范围和限制以[英文说明](README.md)为准；上游框架的完整中文说明见[原仓库](https://github.com/rollroyces/py-idp/blob/main/README.zh-CN.md)。
