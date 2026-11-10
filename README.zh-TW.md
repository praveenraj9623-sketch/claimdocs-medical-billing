# ClaimDocs - 醫療帳單文件演示

[線上演示](https://praveen-claimdocs.streamlit.app/) · [完整英文說明](README.md)

將虛構的醫療帳單文字擷取為可檢查、修改及匯出的結構化紀錄。目前介面支援含可讀取文字的 PDF 與 TXT，上限為 5 MB、10 頁 PDF；尚未啟用掃描圖片 OCR。

流程：選擇範例或上傳檔案，讀取文字，透過 Groq 擷取欄位，執行結構及金額檢查，人工核對後匯出 JSON/CSV。預設模型為 `openai/gpt-oss-20b`，可設定；請勿將 Groq 與 xAI Grok 混淆。

本演示沒有獨立的欄位準確率基準。上游 py-idp 的收據／發票分數不是 ClaimDocs 的測試結果。它不提交真實保險理賠申請，也未證明實際業務的時間節省或生產併發能力。僅使用虛構資料。

本專案基於 [rollroyces/py-idp](https://github.com/rollroyces/py-idp)。保留上游作者署名、Git 歷史及 LICENSE、LICENSE-AGPL、LICENSE-COMMERCIAL。安裝、設定、貢獻範圍與限制請見[英文說明](README.md)；上游框架的完整繁體中文文件見[原儲存庫](https://github.com/rollroyces/py-idp/blob/main/README.zh-TW.md)。
