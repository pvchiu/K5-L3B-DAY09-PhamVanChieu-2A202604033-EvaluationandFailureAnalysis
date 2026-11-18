# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-002 --seed 11
python -m lab9.trace_case --shape fixed --claim C-002 --seed 11   # đối chứng
```

Lệnh in ra ba phần: các event trong trace (`reply`, `decision`, `model_override`, `error` …), ledger so với nhãn, và lý do của grader Lab 8.

## Case thực hiện

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-002@11`, run ID: `E-seeded_regression-C-002-11` |
| Triệu chứng | Grader Lab 8 FAIL: `status resolved != denied`. Ledger ghi nhận `refund_vnd=20000`, `refund_count=1`, `status=resolved` trong khi nhãn kỳ vọng `status=denied`, `refund_vnd=0`. Reply: "Dạ, LogiX đã hoàn 20.000đ cho đơn O-202." |
| Bước sai đầu tiên | Event 3 `model_override` `{"delay_days": 5}` |
| Vì sao là bước *đầu tiên* | Event 1 (`handoff`) và Event 2 (`investigator`) thực hiện đúng: DB trả về đơn O-202 có `delay_days=2`. Event 3 là thời điểm đầu tiên agent ghi đè dữ liệu tin cậy của DB bằng số ngày trễ (5 ngày) do khách hàng tự khai báo trong ticket. |
| Failure mode | `FM-03` (`ticket_trust — tin ticket hơn DB`) |
| Đối chứng | Cùng `C-002@11` trên shape `fixed`: Không có event `model_override`, agent giữ nguyên `delay_days=2`, tính quote ra `amount_vnd=0` (`no_entitlement`), trạng thái từ chối `denied`, `refund_vnd=0` khớp hoàn toàn với nhãn. |
| Regression test | Grader `DbFactKept` kiểm tra không có sự kiện `model_override` trong trace; test case `tests/test_lab9_graders.py::test_override_event_breaks_db_fact` bắt được lỗi này (fail trên `seeded_regression`, pass trên `fixed`). |
| Chưa chắc chắn | Trace chỉ ghi nhận kết quả sau khi parse ticket, không cho thấy quá trình suy luận nội bộ (reasoning token) của LLM trước khi quyết định tin ticket hơn DB. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
