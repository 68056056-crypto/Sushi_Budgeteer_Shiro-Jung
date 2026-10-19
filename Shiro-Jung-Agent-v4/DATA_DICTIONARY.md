# Data dictionary และ provenance

`CSV → import validation → SQLite` โดยตาราง `menu` มี primary key `item_id` และ `metadata` เก็บชื่อไฟล์ SHA256 วันที่ import และลิงก์เกณฑ์ allergen ที่ผู้ใช้ให้ dataset ปัจจุบันมี 42 รายการ (B005 น้ำเปล่า 20 บาท เพิ่มตามราคาที่ผู้ใช้แจ้ง สถานะ unverified) ไม่มี secret หรือประวัติสนทนาในฐานข้อมูล

| คอลัมน์ | ความหมาย |
|---|---|
| item_id | ID ไม่ซ้ำและไม่ว่าง |
| name_th / name_en | ชื่อไทย/อังกฤษ |
| category / plate_color | หมวดอาหาร/สีจานจาก dataset |
| price_baht | ราคาหน่วยบาท ไม่ติดลบ ทศนิยมสูงสุด 2 ตำแหน่ง |
| description_th / keywords | คำบรรยาย/คำค้น; keywords คั่นด้วย `;` |
| allergens_verified | legacy ชื่อคอลัมน์สำหรับ tags คั่นด้วย `;`; ชื่อคอลัมน์ไม่ใช่หลักฐานว่าร้านยืนยันแล้ว |
| source_url | แหล่งอ้างอิงเมนู/ราคา; ชุดข้อมูลที่แนบเว้นว่าง เพราะยังไม่ได้ยืนยันแหล่งข้อมูลรายเมนู |
| price_status | confirmed หรือ unverified; ชุดที่แนบเป็น unverified |
| allergen_status | confirmed หรือ unknown; ชุดที่แนบเป็น unknown |
| allergen_source_url | หลักฐานส่วนผสม/สารก่อภูมิแพ้ของเมนูจากร้าน/ผู้ผลิต ไม่ใช่แค่เอกสารกฎหมายทั่วไป |
| checked_at | วันที่ตรวจหลักฐาน เช่น ISO 8601; เว้นว่างเมื่อยังไม่ตรวจ |

Importer อนุญาต `confirmed` เมื่อมี metadata ที่จำเป็น แต่ไม่สามารถรับรองความน่าเชื่อถือของ URL/ผู้กรอกเองได้ ต้องมีผู้รับผิดชอบตรวจต้นฉบับก่อนตั้งสถานะนั้น อย่าใช้ข้อมูล fixture จาก tests เป็นหลักฐานของร้าน

Vocabulary ปัจจุบันรองรับ `fish`, `crustacean`, `molluscs`, `egg`, `milk`, `gluten`, `soy`, `sesame`, `pork`, `seafood`, `peanut`, `tree_nuts`, `sulphites` เป็นศัพท์ของแอป ยังไม่อ้างว่าตรงรายชื่อ/ขอบเขตตามกฎหมาย อย. ทุกข้อ `pork` เป็นข้อจำกัดอาหารที่อาจใช้ในแอป ไม่ได้อ้างว่าเป็นสารก่อภูมิแพ้ที่กฎหมายกำหนด หาก extractor ส่งชื่อที่ไม่รู้จัก จะคงชื่อไว้และ strict mode ปิดกั้นเมื่อไม่มีหลักฐานเพียงพอ ต้องถาม/ตรวจเพิ่ม ไม่ทิ้งข้อมูลเงียบ ๆ

ข้อมูลว่างไม่ได้หมายถึงปลอดสารก่อภูมิแพ้ การรับรองต้องครอบคลุมคำถามของผู้ใช้และความเสี่ยงที่เกี่ยวข้อง หากพบ allergen นอก vocabulary ใน strict mode ระบบจะไม่ยืนยันชุดแม้เมนูอื่นถูกตั้ง confirmed แล้ว ต้องปรับ mapping จากหลักฐานก่อนใช้

แหล่งเกณฑ์ที่ผู้ใช้ให้: [อย. P450.pdf](https://food.fda.moph.go.th/media.php?id=654869394207416320&name=P450.pdf) ยังอ่านจาก cloud ไม่ได้ (HTTP 403) ต้องตรวจเนื้อหาฉบับเต็มก่อนสรุปข้อกำหนด

การ import ซ้ำจะ replace catalog ไม่ใช่ merge การแก้ CSV ไม่มีผลต่อ DB จน import และการแก้ DB ไม่เขียนกลับ CSV เก็บ revision ของ catalog ในทุก candidate เพื่อป้องกัน verify ผลจากข้อมูลเก่า
