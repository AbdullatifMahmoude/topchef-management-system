// print.js - ملف مسؤول عن طباعة فاتورة الكاشير بحجم 80 ملي -الطباعة
function printReceipt(orderData) {
  const fullOrderNumber = orderData.orderNumber || orderData.order_number || orderData.id || "---";
  const orderNumber = String(fullOrderNumber).includes('-') ? String(fullOrderNumber).split('-').pop() : fullOrderNumber;
  let cashierName = orderData.creator_name || orderData.cashierName || "---";
  const orderDate = orderData.created_at || orderData.order_date;
  
  let formattedDate = "---";
  let formattedTime = "---";

  if (orderDate) {
    const dateObj = new Date(orderDate);
    if (!isNaN(dateObj)) {
      formattedDate = dateObj.toLocaleDateString('ar-EG');
      if (String(orderDate).length > 10) {
        formattedTime = dateObj.toLocaleTimeString('ar-EG', {hour: '2-digit', minute:'2-digit'});
      }
    } else {
      formattedDate = orderDate;
    }
  }

  // Desktop prints through native Python only; QR is generated offline in printer.py.
  if (window.pywebview && window.pywebview.api && window.pywebview.api.print_silent) {
    console.log("Desktop runtime detected. Sending order data to native print bridge...");
    window.pywebview.api.print_silent("", orderData);
    return;
  }

  const iframe = document.createElement('iframe');
  iframe.style.display = 'none';
  document.body.appendChild(iframe);
  const doc = iframe.contentWindow.document;
  
  let rawAddr = orderData.customerAddress || orderData.customer_address || orderData.address || orderData.customer_notes || '';
  let printAddrText = (typeof rawAddr === 'object' && rawAddr !== null) ? (rawAddr.address || rawAddr.address_line || rawAddr.full_address || rawAddr.street || rawAddr.name || '') : rawAddr;
  const isDoublePrint = false; // (orderData.orderType === 'delivery' || orderData.order_type === 'delivery' || orderData.orderType === 'takeaway' || orderData.order_type === 'takeaway');

  const receiptContent = `
      <div class="receipt-header">
        <div class="header-row" style="display:flex; justify-content:space-between; align-items:center; min-height:70px; border-bottom:1px dashed #000; padding-bottom:5px;">
          <!-- Left: Date/Time -->
          <div style="text-align:right; font-size:11px; font-weight:900; line-height:1.3; flex:1;">
            <div>${formattedDate}</div>
            <div>${formattedTime}</div>
          </div>
          
          <!-- Middle: Order Number -->
          <div style="flex:2; text-align:center;">
            <h1 class="order-number" style="display:inline-block; font-size:18px; font-weight:900; border:2px solid #000; padding:3px 6px; border-radius:5px; margin:0 5px;">
              #${orderNumber}
            </h1>
          </div>
          
          <!-- Right: QR Code -->
          <div style="flex:1; text-align:left;">
            <img src="https://api.qrserver.com/v1/create-qr-code/?size=150x150&data=https://top-chef-resturant.vercel.app/" 
                 alt="QR" style="width:55px; height:55px; display:block; margin-left:auto;" />
          </div>
        </div>
        
        <div class="info-line" style="display:flex; justify-content:space-between; margin-top:8px; border-top:1px dashed #000; padding-top:4px; font-size:12px; font-weight:bold;">
          <span>كاشير: ${cashierName}</span>
          <span>${getOrderTypeLabel(orderData.orderType || orderData.order_type)}</span>
        </div>
        
        ${(orderData.orderType === 'delivery' || orderData.order_type === 'delivery') && (orderData.delivery_person_name || (orderData.selectedDelivery && orderData.selectedDelivery.name)) ? `
        <div class="info-line" style="border:none; margin-top:2px;">
          <span style="width:100%">مندوب: ${orderData.delivery_person_name || (orderData.selectedDelivery && orderData.selectedDelivery.name)}</span>
        </div>` : ''}
      </div>
      
      <table class="items">
        <thead>
          <tr>
            <th class="qty">ك</th>
            <th class="item-name">الصنف</th>
            <th class="price">سعر</th>
            <th class="total">إجمالي</th>
          </tr>
        </thead>
        <tbody>
          ${(orderData.cart || []).map(c => `
            <tr>
              <td class="qty">${c.qty || 0}</td>
              <td class="item-name">${c.item ? c.item.name : '---'}</td>
              <td class="price">${Number(c.item ? c.item.price : 0).toFixed(0)}x </td>
              <td class="total">${((c.qty || 0) * (c.item ? c.item.price : 0)).toFixed(0)}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      
      <div class="totals">
        <div class="totals-row">
          <span>المجموع:</span>
          <span>${Number(orderData.itemsTotal || orderData.subtotal || 0).toFixed(2)}</span>
        </div>
        ${((orderData.order_type === 'delivery' || orderData.orderType === 'delivery') && (orderData.delivery_fee || orderData.selectedDeliveryFee)) ? `
          <div class="totals-row">
            <span>التوصيل:</span>
            <span>${Number(orderData.delivery_fee || orderData.selectedDeliveryFee || 0).toFixed(2)}</span>
          </div>
        ` : ''}
        ${((orderData.order_type === 'hall' || orderData.order_type === 'dine_in' || orderData.orderType === 'dine_in') && (orderData.delivery_fee || orderData.selectedDineInFee)) ? `
          <div class="totals-row">
            <span>الصالة:</span>
            <span>${Number(orderData.delivery_fee || orderData.selectedDineInFee || 0).toFixed(2)}</span>
          </div>
        ` : ''}
        ${(orderData.discount_amount && Number(orderData.discount_amount) > 0) ? `
          <div class="totals-row">
            <span>الخصم${orderData.discount_reason ? ` (${orderData.discount_reason})` : ''}:</span>
            <span>- ${Number(orderData.discount_amount).toFixed(2)}</span>
          </div>
        ` : ''}
        <div class="totals-row grand">
          <span>الإجمالي النهائي:</span>
          <span>${Number(orderData.total_amount || orderData.grandTotal || 0).toFixed(2)} ج.م</span>
        </div>
      </div>

      ${(orderData.customerName || orderData.customer_name || orderData.customerPhone || orderData.customer_phone || printAddrText) ? `
      <div class="customer-info">
        <div class="customer-info-title">بيانات العميل</div>
        ${(orderData.customerName || orderData.customer_name) ? `
        <div class="customer-info-row">
          <span> اسم العميل :${orderData.customerName || orderData.customer_name}</span>
        </div>` : ''}
        ${(orderData.customerPhone || orderData.customer_phone) ? `
        <div class="customer-info-row">
          <span style="direction:ltr"> رقم التليفون :${orderData.customerPhone || orderData.customer_phone}</span>
        </div>` : ''}
        ${(printAddrText) ? `
        <div class="customer-info-row">
          <span> العنوان :${printAddrText}</span>
        </div>` : ''}
       
      </div>` : ''}

      <div class="footer">
        <p>مزلقان هرية رزنة - الزقازيق - الشرقية</p>
        <p>01212758001 - 01129820007</p>
        <p style="margin-top: 5px;">شكراً لزيارتكم - Top Chef</p>
      </div>
  `;

  const html = `
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8">
      <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @page { margin: 0; }
        body {
          font-family: 'Cairo', sans-serif, Arial;
          width: 72mm;
          margin: 0 auto;
          padding: 2mm;
          font-size: 11px;
          color: #000;
          background: #fff;
        }
        .receipt-header {
          border-bottom: 1px dashed #000;
          padding-bottom: 4px;
          margin-bottom: 6px;
        }
        .header-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
        }
        .order-number { font-size: 18px; font-weight: 900; }
        .info-line {
          display: flex;
          justify-content: space-between;
          font-size: 11px;
          font-weight: bold;
          margin-top: 3px;
          border-top: 1px solid #eee;
          padding-top: 2px;
        }
        .items { width: 100%; border-collapse: collapse; margin-top: 5px; }
        .items th { border-bottom: 1px solid #000; font-size: 10px; padding: 2px; }
        .items td { border-bottom: 1px solid #eee; padding: 4px 2px; font-size: 11px; font-weight: bold; }
        .items .item-name { text-align: right; width: 50%; white-space: normal; overflow-wrap: anywhere; word-break: break-word; line-height: 1.35; }
        .items .qty { text-align: center; width: 10%; }
        .items .price { text-align: center; width: 20%; }
        .items .total { text-align: left; width: 20%; }
        
        .totals { margin-top: 6px; border-top: 1px solid #000; padding-top: 4px; }
        .totals-row { display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 2px; font-weight: bold; }
        .totals-row.grand { font-size: 15px; font-weight: 900; margin-top: 4px; border-top: 1px dashed #000; padding-top: 4px; }

        .customer-info { margin-top: 8px; border: 1px dashed; padding: 4px 6px; border-radius: 4px; }
        .customer-info-title { font-size: 11px; font-weight: 900; text-align: center; margin-bottom: 3px; }
        .customer-info-row { font-size: 11px; font-weight: bold; margin-bottom: 2px; }
        
        .footer { text-align: center; margin-top: 10px; font-size: 10px; border-top: 1px dashed #777; padding-top: 6px; }
        .footer p { margin-bottom: 2px; }

        .receipt-wrapper {
          page-break-after: always;
          width: 100%;
          display: block;
        }
        .receipt-wrapper:last-child { page-break-after: auto; }
      </style>
    </head>
    <body>
      <div class="receipt-wrapper">${receiptContent}</div>
      ${isDoublePrint ? `<div class="receipt-wrapper" style="margin-top:10mm; border-top:1px dashed #ccc; padding-top:5mm;">${receiptContent}</div>` : ''}
    </body>
    </html>
  `;
  
  doc.open();
  doc.write(html);
  doc.close();
  
  // Fallback for browser/web runtime
  setTimeout(() => {
    iframe.contentWindow.focus();
    iframe.contentWindow.print();
    setTimeout(() => { if (iframe.parentElement) document.body.removeChild(iframe); }, 1000);
  }, 500);
}

function getOrderTypeLabel(type) {
  if (type === 'delivery') return 'دليفري';
  if (type === 'takeaway') return 'تيك اواي';
  if (type === 'dine_in' || type === 'hall') return 'صالة';
  return 'غير محدد';
}
