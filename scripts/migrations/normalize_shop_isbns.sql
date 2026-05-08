-- One-shot: strip dashes and spaces from shop_books.isbn so the matcher
-- can join shop_books.isbn = book_isbns.isbn directly.
UPDATE shop_books
   SET isbn = REPLACE(REPLACE(isbn, '-', ''), ' ', '')
 WHERE isbn IS NOT NULL
   AND (isbn LIKE '%-%' OR isbn LIKE '% %');
