import { apiInitializer } from "discourse/lib/api";

export default apiInitializer((api) => {
  api.decorateCooked(($elem, helper) => {
    if (!helper) return;

    const embedRegex = /\[moxfield\]([A-Za-z0-9_-]+)\[\/moxfield\]/g;

    $elem[0].querySelectorAll("p").forEach(el => {
      if (!embedRegex.test(el.innerHTML)) return;
      embedRegex.lastIndex = 0;

      el.innerHTML = el.innerHTML.replace(embedRegex, (match, deckId) => {
        return `
          <div class="moxfield-embed-wrapper">
            <iframe
              src="https://www.moxfield.com/embed/${deckId}"
              class="moxfield-embed"
              frameborder="0"
              allowfullscreen
              loading="lazy">
            </iframe>
          </div>`;
      });
    });
  }, { id: "moxfield-embed" });
});
