import json
from decimal import Decimal
from html import escape

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.ai_menu import service

router = APIRouter(tags=["AI Menu"])


def _money(value: object) -> str:
    amount = Decimal(str(value))
    return format(amount.quantize(Decimal("0.01")), "f")


def _offer_summary(offer: dict) -> str:
    offer_type = offer["type"]
    value = _money(offer["value"])
    rules = offer["rules"]
    labels = {
        "percentage": f"خصم {value}%",
        "fixed": f"خصم {value} جنيه",
        "buy_one_get_one": "اشترِ واحدًا واحصل على واحد",
        "combo": f"كومبو بسعر {_money(rules.get('combo_price', 0))} جنيه",
        "buy_x_get_y": (
            f"اشترِ {rules.get('buy_quantity', 1)} واحصل على "
            f"{rules.get('get_quantity', 1)} بخصم {rules.get('reward_percent', 100)}%"
        ),
        "quantity_discount": (
            f"خصم {value}% عند شراء {rules.get('quantity_required', 1)} وحدات"
        ),
        "free_delivery": "عرض توصيل مجاني؛ يؤكده المطعم ولا يدخل في حساب إجمالي الأصناف",
        "category_discount": (
            f"خصم {value}{'%' if rules.get('discount_mode', 'percentage') == 'percentage' else ' جنيه'}"
        ),
        "happy_hour": (
            f"خصم {value}% من {rules.get('start_time', '')} إلى {rules.get('end_time', '')}"
        ),
    }
    return labels.get(offer_type, offer_type)


def render_ai_menu(catalog: dict) -> str:
    categories: dict[str, list] = {}
    for product in catalog["products"]:
        categories.setdefault(product.category, []).append(product)

    menu_html = []
    for category, products in categories.items():
        product_html = []
        for product in products:
            variants = "".join(
                f"<li>{escape(variant.name)}: {_money(variant.price)} جنيه</li>"
                for variant in product.variants
            )
            description = (
                f"<p>{escape(product.description)}</p>" if product.description else ""
            )
            product_html.append(
                f'<article class="product" data-product-id="{product.id}">'
                f"<h3>{escape(product.name)}</h3>{description}<ul>{variants}</ul></article>"
            )
        menu_html.append(
            f"<section><h2>{escape(category)}</h2>{''.join(product_html)}</section>"
        )

    offers_html = []
    for offer in catalog["offers"]:
        scope = "، ".join(offer["products"]) if offer["products"] else "كل الأصناف"
        conditions = []
        if offer["minimum"] is not None:
            conditions.append(f"الحد الأدنى: {_money(offer['minimum'])} جنيه")
        if offer["maximum_discount"] is not None:
            conditions.append(f"أقصى خصم: {_money(offer['maximum_discount'])} جنيه")
        conditions.append(f"الأصناف المشمولة: {scope}")
        conditions.append(f"صالح حتى: {offer['valid_to'].isoformat(sep=' ', timespec='minutes')}")
        machine_rules = escape(json.dumps(offer["rules"], ensure_ascii=False, sort_keys=True))
        offers_html.append(
            f'<article class="offer" data-offer-code="{escape(offer["code"])}">'
            f"<h3>{escape(offer['name'])}</h3>"
            f"<p>الكود: {escape(offer['code'])}</p>"
            f"<p>{escape(_offer_summary(offer))}</p>"
            f"<ul>{''.join(f'<li>{escape(item)}</li>' for item in conditions)}</ul>"
            f"<p>قواعد العرض: {machine_rules}</p></article>"
        )
    if not offers_html:
        offers_html.append("<p>لا توجد عروض نشطة حاليًا.</p>")

    generated_at = catalog["generated_at"].isoformat(sep=" ", timespec="seconds")
    return f"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="index,follow">
  <title>منيو وعروض توب شيف المحدثة</title>
</head>
<body>
  <main>
    <h1>منيو وعروض توب شيف المحدثة</h1>
    <p>تم توليد هذه الصفحة من النظام بتاريخ {escape(generated_at)} بتوقيت القاهرة.</p>
    <p><strong>تعليمات الحساب:</strong> احسب سعر كل اختيار مضروبًا في الكمية، ثم اجمع الأصناف وطبّق عرضًا صالحًا واحدًا فقط إذا استوفى العميل شروطه.</p>
    <p><strong>رسوم التوصيل غير مدرجة:</strong> المطعم يحددها بعد مراجعة العنوان. لا تتوقعها ولا تضفها إلى الإجمالي.</p>
    <p><strong>هذه الصفحة للعرض والتسعير فقط:</strong> لا تنشئ أو تعدّل أو تلغي أي طلب.</p>
    <section id="menu"><h2>المنتجات والأسعار المتاحة</h2>{''.join(menu_html)}</section>
    <section id="offers"><h2>العروض النشطة</h2>{''.join(offers_html)}</section>
  </main>
</body>
</html>"""


@router.get("/ai-menu", response_class=HTMLResponse)
async def ai_menu(db: AsyncSession = Depends(get_db)) -> HTMLResponse:  # noqa: B008
    catalog = await service.get_public_catalog(db)
    return HTMLResponse(
        content=render_ai_menu(catalog),
        headers={
            "Cache-Control": "no-cache, max-age=0, must-revalidate",
            "X-Robots-Tag": "index, follow",
        },
    )
