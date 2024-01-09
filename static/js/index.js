var DICT={};
var timer, count_symbol=0, count_word=0, count_error=0; // Таймер
var spans=0;
let currentIndex = -1; // Индекс текущего выделенного слова
let atribut = 'onclick';
let atr = 'click';
if ('ontouchstart' in window) {
    atribut = 'ontouchend';
    atr = 'touchend';
}

//Сохранение положения курсора
function saveSelection(containerEl) {
    var range = window.getSelection().getRangeAt(0);
    var preSelectionRange = range.cloneRange();
    preSelectionRange.selectNodeContents(containerEl);
    preSelectionRange.setEnd(range.startContainer, range.startOffset);
    var start = preSelectionRange.toString().length;

    return {
        start: start,
        end: start + range.toString().length
    };
}

//Востановление положения курсора
function restoreSelection(containerEl, savedSelection) {
    var charIndex = 0;
    var range = document.createRange();
    range.setStart(containerEl, 0);
    range.collapse(true);
    var nodeStack = [containerEl], node, foundStart = false, stop = false;

    while (!stop && (node = nodeStack.pop())) {
        if (node.nodeType == 3) {
            var nextCharIndex = charIndex + node.length;
            if (!foundStart && savedSelection.start >= charIndex && savedSelection.start <= nextCharIndex) {
                range.setStart(node, savedSelection.start - charIndex);
                foundStart = true;
            }
            if (foundStart && savedSelection.end >= charIndex && savedSelection.end <= nextCharIndex) {
                range.setEnd(node, savedSelection.end - charIndex);
                stop = true;
            }
            charIndex = nextCharIndex;
        } else {
            var i = node.childNodes.length;
            while (i--) {
                nodeStack.push(node.childNodes[i]);
            }
        }
    }

    var sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
}


//Удаление стилей текста перед вставкой и разделение на абзацы
function stripStyles(e) {
    e.preventDefault();
    const clipboardData = e.clipboardData || window.clipboardData;
    const pastedData = clipboardData.getData('text/plain');
    const paragraphs = pastedData.split('\n');

    let formattedText = '';

    for (let i = 0; i < paragraphs.length; i++) {
        formattedText += `${paragraphs[i]}<br> `;
    }
    formattedText = formattedText.replace(/[\r\n]/g, '');
    document.execCommand('insertHTML', false, formattedText);
}


var text_content=document.getElementById('text_content');

const placeholder = document.getElementById('placeholder');
const inform = document.getElementById('inform');
const btn1=document.getElementById('error_btn');
const btn2=document.getElementById('error_btn2');

var divCountSymbol=document.getElementById('count_symbol');
var divCountWord=document.getElementById('count_word');
var divCountError=document.getElementById('count_error');

divCountSymbol.textContent=count_symbol;
divCountWord.textContent=count_word;
divCountError.textContent=count_error;


//отслеживание изменений
text_content.addEventListener('input', function(event) {
    clearTimeout(timer); // Сбрасываем предыдущий таймер

    count_symbol=text_content.textContent.length;
    togglePlaceholder();

    let marks =[' ', ',', '.', '?', '!', ':', ';'];
    if(marks.includes(event.data)){
        clearTimeout(timer); // Сбрасываем предыдущий таймер
        timer = setTimeout(add_word, 0);
    }else{
        timer = setTimeout(add_word, 3000);
    }
});


//Добавление новых слов в DICT
function add_word(){
    console.log('таймер сработал');

    let containers = document.getElementById('rightWordDiv');
    if (containers) {
        text_content.removeChild(containers);
    }
    let text=text_content.innerHTML;

    if(text.includes('<div>')){
        let newText = text.replace(/<div>/g, "<br> ");
        newText = newText.replace(/<\/div>/g, "");
        let savedSelection = saveSelection(text_content);
        text_content.innerHTML=newText;
        restoreSelection(text_content, savedSelection);
        text=text_content.innerHTML;
    }


    var regex = /(<span>.*?<\/span>)/g;
    var words = text.split(regex);
    words = words.filter(function(word) {
        return word !== "";
    });


    for(i=0; i < words.length; i++){
        if (!(words[i].includes('<span>') || words[i].includes('<span class="dropdown-trigger" '+ atribut +'="toggleListDisplayblock(event)">')) && words[i] !== '<br>') {
            words[i] = '<span>' + words[i] + '</span>';
        }
    }

    words = WordToSpan(words);

    var savedSelection = saveSelection(text_content);
    text_content.innerHTML=words.join('');
    restoreSelection(text_content, savedSelection);

    var array_word=splitTextIntoWords(text_content.innerText);

    count_word=array_word.length;
    divCountWord.textContent=count_word;

    for (let i = 0; i < array_word.length; i++) {
        // Проверяем, есть ли слово уже в объекте
        if (!DICT.hasOwnProperty(array_word[i])) {
            // Если слова нет, то добавляем его в объект
            DICT[array_word[i]] = null;
        }
    }
    console.log('DICT'+DICT);
    sendOnBackend();
}


function WordToSpan(words){
    for (let i=0; i < words.length; i++){
        let word = words[i].replace(/<\/?span[^>]*>/g, '');
        if (word.trim()!=="" && word.split(/(&nbsp;|\s)/).filter(Boolean).length > 1){
            word = word.split(/(&nbsp;|\s)/).filter(Boolean);
            word = word.filter(function(word1) {
                return word1 !== "";
            });

            for(let j=0; j < word.length; j++){
                if (!word[j].includes('<span>') && word[j] !== '<br>') {
                    if (word[j].includes("<br>")){
                        word[j] = word[j].replace(/<\/?[^>]+(>|$)/g, "");
                        word[j] = '<span>' + word[j] + '</span><br>';
                    }else{
                        word[j] = '<span>' + word[j] + '</span>';
                    }
                }
            }
            words.splice(i, 1, ...word);
        }

        if (i < words.length-1 && words[i] !== '<br>' && words[i+1] !== '<br>' && words[i].replace(/<\/?span[^>]*>/g, '') !== ' ' && words[i+1].replace(/<\/?span[^>]*>/g, '') !== ' ' && words[i].replace(/<\/?span[^>]*>/g, '') !== '&nbsp;' && words[i+1].replace(/<\/?span[^>]*>/g, '') !== '&nbsp;'){
            let new_span='<span>' + words[i].replace(/<\/?span[^>]*>/g, '') + words[i+1].replace(/<\/?span[^>]*>/g, '') + '</span>';
            words.splice(i, 2, new_span);
            i--;
        }
    }
    return words;
}


//разделение текста на слова
function splitTextIntoWords(text) {
    // Удаляем знаки препинания
    const cleanText = text.replace(/[.,!?;:()"“”'–−—«»]/g, '');

    // Разделяем текст на слова
    const words = cleanText.split(/\s+/);

    // Удаляем возможные пустые строки после удаления знаков препинания
    return words.filter(word => word.length > 0);
}


//отправка на сервер не проверенных слов
function sendOnBackend(){
    if(Object.keys(DICT).length===0){
        console.log('DICT пуст')
    }else {
        console.log('DICT:',DICT);
        var null_array=[];
        var k=0;
        for (const key in DICT) {
            if (DICT.hasOwnProperty(key) && DICT[key] === null) {
                k++;
                null_array.push(key);
                if(null_array.length===100){
                    request_server(null_array);
                    null_array=[];
                }
            }
        }
        if(null_array.length !== 0){
            request_server(null_array);
            null_array=[];
        }
        if(k===0){
            correctDivContentText();

            count_error=countTags();
            divCountError.textContent=count_error;
            if(count_error>1){
                btn1.style.display='inline-block';
                btn2.style.display='inline-block';

            }else{
                btn1.style.display='none';
                btn2.style.display='none';
            }
        }
    }
}




function request_server(check_candidates){
    const dataToSend = {unverified_words:check_candidates};
    const requestOptions = {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(dataToSend),
    };

    fetch('/data_processing', requestOptions)
    .then(response => response.json())
    .then(data => {
        // Обрабатываем ответ от сервера
        updateDICT(data.message);
    })
    .catch(error => {
        // Обрабатываем ошибку
        console.error('Ошибка:', error);
    });
}


//Обнавление DICT
function updateDICT(new_array){
    for(var i=0; i < new_array.length; i++){
        DICT[new_array[i].word]=new_array[i].variants;
    }
    correctDivContentText();

    count_error=countTags();
    divCountError.textContent=count_error;
    if(count_error>1){
        btn1.style.display='inline-block';
        btn2.style.display='inline-block';
    }else{
        btn1.style.display='none';
        btn2.style.display='none';
    }
}


//Подчеркивание слов
function correctDivContentText(){
    var spanElements = text_content.getElementsByTagName("span");
    var word_span;
    for (var i = 0; i < spanElements.length; ++i) {
        word_span=spanElements[i].textContent;
        const cleanWord = word_span.replace(/[.,!?;:()"“”'–−«»]/g, "");
        if (!(spanElements[i].classList.contains("dropdown-trigger")) && spanElements[i].textContent != ' ') {

            if (DICT.hasOwnProperty(cleanWord) && DICT[cleanWord] !== null && DICT[cleanWord].length > 0) {
                spanElements[i].classList.add("dropdown-trigger");
                spanElements[i].setAttribute(atribut, "toggleListDisplayblock(event)");
            }
        }else if(spanElements[i].classList.contains("dropdown-trigger") && DICT[cleanWord].length === 0){
            spanElements[i].removeAttribute("class");
            spanElements[i].removeAttribute(atribut);
        }
    }
 }


DivCorrect=document.createElement("div");
DivCorrect.id = "rightWordDiv";
DivCorrect.setAttribute('contenteditable', 'false');

DivCorrect.innerHTML=`<div id="lineOne"><img src="/static/images/!.png" alt="">    Ихтимал булған төҙәтмә</div>`;

const list_v = document.createElement("ul");
list_v.id="dropdownlist";
list_v.setAttribute(atribut, "handleOptionClick(event)");
DivCorrect.appendChild(list_v);

var ignorButton = document.createElement('button');
ignorButton.id = 'ignor';
ignorButton.setAttribute(atribut, 'ignorError(event)');

var img = document.createElement('img');
img.id = 'ignor_img';
img.src = '/static/images/new_ignor.png';
img.alt = '';

var leave= document.createElement('span');
leave.id = 't_ig';
leave.className = 't_id'
leave.innerText = 'Ҡалдырырға';

ignorButton.appendChild(img);
ignorButton.appendChild(leave);

DivCorrect.appendChild(ignorButton);
DivCorrect.style.display='block';



function toggleListDisplayblock(event) {
    var cleanWord = event.target.textContent.replace(/[.,!?;:()"“”'–−«»]/g, "");

    list_v.innerHTML = "";
    for (let i = 0; i < DICT[cleanWord].length; i++) {
        const option = document.createElement("li");
        option.innerHTML = `${DICT[cleanWord][i]}`;
        list_v.appendChild(option);
    }

    event.target.insertAdjacentElement('afterend', DivCorrect);

    let rect1 = text_content.getBoundingClientRect();
    var spanRect = event.target.getBoundingClientRect();
    // Позиционируем rightWordDiv под span
    DivCorrect.style.left = spanRect.left - rect1.left + 'px';

    let rect2 = DivCorrect.getBoundingClientRect();
    let overlapRight = rect2.right - rect1.right;

    if (overlapRight > 0) {
        DivCorrect.style.right='0px';
        DivCorrect.style.left='auto';
    }
}


function handleOptionClick(event) {
    if(currentIndex>-1){
        currentIndex--;
    }
    let span_teg=event.currentTarget.parentElement.previousElementSibling;
    if (event.target.tagName === "LI") {
        const selectedOption = event.target.textContent;

        let old_text=span_teg.textContent.replace(/[.,!?;:()"“”'–−«»]/g, "");
        span_teg.textContent = span_teg.textContent.replace(new RegExp(old_text, 'g'), selectedOption);

        span_teg.removeAttribute("class");
        span_teg.removeAttribute(atribut);
        let cleanWord = selectedOption.replace(/[.,!?;:()"“”'–−«»]/g, "");
        DICT[cleanWord]=[];
        add_word();
    }
    count_error=countTags();
    divCountError.textContent=count_error;
    if(count_error>1){
        btn1.style.display='inline-block';
        btn2.style.display='inline-block';

    }else{
        btn1.style.display='none';
        btn2.style.display='none';
    }
}


function ignorError(event){
    if(currentIndex>-1){
        currentIndex--;
    }
    let span_teg=event.currentTarget.parentElement.previousElementSibling;
    let ignorWord=event.currentTarget.parentElement.previousElementSibling.textContent;
    let cleanWord = ignorWord.replace(/[.,!?;:()"“”'–−«»]/g, "");
    span_teg.textContent=`${ignorWord}`;
    span_teg.removeAttribute("class");
    span_teg.removeAttribute(atribut);
    DICT[cleanWord]=[];

    count_error=countTags();
    divCountError.textContent=count_error;
    if(count_error>1){
        btn1.style.display='inline-block';
        btn2.style.display='inline-block';

    }else{
        btn1.style.display='none';
        btn2.style.display='none';
    }
}


var dbl_btn=document.getElementById('dbl_btn');

document.addEventListener(atr, function (event) {
    var containers = document.getElementById('rightWordDiv');

    if (containers && containers !== event.target && event.target !== containers.previousElementSibling && dbl_btn!==event.target && !dbl_btn.contains(event.target)) {
        text_content.removeChild(containers);
    }
});


// Функция для отображения/скрытия начальной подсказки и информации
function togglePlaceholder() {
    const placeholder = document.getElementById('placeholder');
    const inform = document.getElementById('inform');
    if (text_content.textContent === '') {
        placeholder.style.display = 'block';
        inform.style.display='none';
    } else {
        placeholder.style.display = 'none';
        inform.style.display='block';
        divCountSymbol.textContent=count_symbol;

        //count_error=3;
        if(count_error>1){
            btn1.style.display='inline-block';
            btn2.style.display='inline-block';

        }else{
            btn1.style.display='none';
            btn2.style.display='none';
        }
    }
}


//количество ошибок в тексте
function countTags() {
    spans = text_content.querySelectorAll('.dropdown-trigger');
    return spans.length;
}


let back_btn=document.getElementById('error_btn');
let next_btn=document.getElementById('error_btn2');
let copy_btn=document.getElementById('copy_text_btn');
let clean_btn=document.getElementById('clean_text');
next_btn.setAttribute(atribut, "nextWord()");
back_btn.setAttribute(atribut, "backWord()");
copy_btn.setAttribute(atribut, "CopyText()");
clean_btn.setAttribute(atribut, "cleanTextContainer()");


function cleanTextContainer(){
    text_content.innerHTML='';
    DICT={};
    placeholder.style.display = 'block';
    inform.style.display='none';
    divCountSymbol.textContent='0';
    divCountWord.textContent='0';
    divCountError.textContent='0';
    btn1.style.display='none';
    btn2.style.display='none';
    currentIndex = -1;
}


function CopyText(){
    text_content.focus();
    document.execCommand('selectAll'); // Выделить весь текст
    document.execCommand('copy'); // Скопировать выделенный текст
    window.getSelection().removeAllRanges();
}


function next_back(event) {
    var cleanWord = event.textContent.replace(/[.,!?;:()"“”'–−«»]/g, "");

    list_v.innerHTML = "";
    for (let i = 0; i < DICT[cleanWord].length; i++) {
        const option = document.createElement("li");
        option.innerHTML = `${DICT[cleanWord][i]}`;
        list_v.appendChild(option);
    }

    event.insertAdjacentElement('afterend', DivCorrect);

    let rect1 = text_content.getBoundingClientRect();
    var spanRect = event.getBoundingClientRect();
    // Позиционируем rightWordDiv под span
    DivCorrect.style.left = spanRect.left - rect1.left + 'px';

    let rect2 = DivCorrect.getBoundingClientRect();
    let overlapRight = rect2.right - rect1.right;

    if (overlapRight > 0) {
        DivCorrect.style.right='0px';
        DivCorrect.style.left='auto';
    }
}


// Функция для выделения следующего слова
function nextWord() {
    if (currentIndex < spans.length - 1) {
        if(currentIndex === -1){
            currentIndex++;
            next_back(spans[currentIndex]);
        }else{
            let list=spans[currentIndex].nextElementSibling;
            if (list.tagName === 'DIV'){
                text_content.removeChild(list);
            }
            currentIndex++;
            next_back(spans[currentIndex]);
        }
    }
}

  // Функция для выделения предыдущего слова
function backWord() {
    if (currentIndex > 0) {
        let list=spans[currentIndex].nextElementSibling;
        if (list.tagName === 'DIV'){
            text_content.removeChild(list);
        }
        currentIndex--;
        next_back(spans[currentIndex]);
    }
}