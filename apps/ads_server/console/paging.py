from django.core.paginator import Paginator

PER_PAGE = 20


def page_of(items, request, per_page=PER_PAGE):
    """`?page=` 의 쪽. 숫자가 아니면 첫 쪽, 넘치면 마지막 쪽(`Paginator.get_page`). 화면은 `console/_pager.html` 로 쪽 이동을 그린다."""
    return Paginator(items, per_page).get_page(request.GET.get("page"))
