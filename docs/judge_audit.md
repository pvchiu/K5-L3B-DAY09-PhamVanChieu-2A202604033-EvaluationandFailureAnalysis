# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5`

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | ĐẠT (0.757 ≥ 0.6, 0.857 ≥ 0.8, 0.800 ≥ 0.7) | dùng |
| helpful | 100 | 0.375 | 1.000 | 0.300 | KHÔNG ĐẠT (Recall 0.300 < 0.7, κ 0.375 < 0.6) | loại |

## ≥5 case audit thủ công (trên dữ liệu judge_tone)

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú & Đề xuất sửa rubric |
|---|---|---|---|---|---|
| 1 | `H-008`: "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | Người đúng | Ngôn từ suồng sã, xưng hô cá nhân (em/anh) và chêm từ cảm thán "nha", "check giúp em" vi phạm quy chuẩn CSKH chuyên nghiệp. **Sửa rubric:** Quy định rõ đại từ nhân xưng bắt buộc phải là "LogiX" và "quý khách / anh/chị". |
| 2 | `H-029`: "Dạ, vui lòng chờ. Hệ thống đang xử lý, không cần nhắn thêm." | PASS | FAIL | Người đúng | Câu mang sắc thái gắt gỏng, thiếu kiên nhẫn và cộc lốc ("không cần nhắn thêm"). Judge bị đánh lừa bởi từ "Dạ, vui lòng chờ". **Sửa rubric:** Bổ sung tiêu chí cấm các cụm từ thể hiện thái độ tiêu cực, từ chối tương tác với khách. |
| 3 | `H-042`: "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | Người đúng | Câu trả lời lịch sự, có dạ/ạ và cung cấp thông tin thời gian đối soát rõ ràng. Judge phạt khắt khe do nghi ngờ đưa mốc thời gian. **Sửa rubric:** Cho phép thông báo khung thời gian đối soát hoàn tiền tiêu chuẩn của ngân hàng/ví điện tử. |
| 4 | `H-070`: "Dạ, LogiX đã hoàn 90.000đ cho đơn O-909 ạ 😂😂" | PASS | FAIL | Người đúng | Sử dụng emoji cợt nhả (`😂😂`) trong ngữ cảnh xử lý khiếu nại khách hàng, vi phạm tính trang nghiêm của CSKH. Judge bỏ qua emoji khi chấm. **Sửa rubric:** Cấm sử dụng emoji cợt nhả/thiếu nghiêm túc trong mọi phản hồi CSKH. |
| 5 | `H-094`: "Da, LogiX da hoan 40.000đ cho don O-341, xin loi vi su bat tien." | PASS | FAIL | Người đúng | Viết tiếng Việt không dấu, vi phạm tiêu chuẩn giao tiếp chính thức của doanh nghiệp. Judge chỉ phân tích ngữ nghĩa nên bỏ sót. **Sửa rubric:** Thêm điều kiện tiên quyết: Phản hồi bắt buộc phải sử dụng tiếng Việt có dấu chuẩn chính tả. |

## Kết luận
- **Tiêu chí bị loại và lý do:**
  `judge_helpful` bị **loại bỏ hoàn toàn** không được dùng làm gate do không đạt ngưỡng an toàn:
  - Ma trận nhầm lẫn: `{"tp": 9, "fp": 0, "fn": 21, "tn": 70}`.
  - Recall chỉ đạt **0.300** (bỏ lọt tới 21 trên tổng số 30 trường hợp FAIL thực tế, tỉ lệ bỏ sót lỗi lên tới 70%).
  - Hệ số tương đồng Cohen's Kappa chỉ đạt **0.375** (dưới ngưỡng sàn 0.6 rất xa).
  - Tỉ lệ lỗi quan sát thấy (observed fail rate) chỉ là 0.09 trong khi sau khi hiệu chỉnh Rogan-Gladen tỉ lệ lỗi thật là 0.30. Judge này quá dễ dãi và tạo ra ảo tưởng an toàn nguy hiểm.
- **Tiêu chí được chấp nhận:**
  `judge_tone` đạt `kappa = 0.757`, `Precision = 0.857`, `Recall = 0.800`, đủ điều kiện làm gate chất lượng giọng văn.
- **Rủi ro còn lại:**
  Judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng); cần liên tục thu thập nhãn từ con người trên các phản hồi mới trong production để xây dựng tập held-out thực thụ và định kỳ recalibrate.
