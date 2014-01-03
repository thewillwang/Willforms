var xx = xx||{}
xx = {
	text:{},
	selection:{},
	date:{},
	number:{},
	del : function(number){
		$('div').remove("#content"+number);
	},
	util:{}
};
/**************************************/
xx.date ={
	// insert
	insert : function(number){
		var div = document.getElementById(xx.util.insert(number,"FormType/Date.html"));
		var replacetil = div.innerHTML;
		replacetil = replacetil.replace(/_number__/g,  number+"");
		div.innerHTML = replacetil;
		$("#dataName" +number).html(HtmlEncode($("#title"+number).html()+number));
	},
	//edit
	edit : function(number){
		$( "#dialog" ).html( 
		"Title: <textarea id=\""+"title"+number+"update\">"+$("#title"+number).html()+"</textarea><br/>"+
		"Hint: <textarea id=\""+"Hint"+number+"update\">"+$("#Hint"+number).html()+"</textarea><br/>"+
		"Data Name: <textarea id=\""+"dataName"+number+"update\">"+$("#dataName"+number).html()+"</textarea><br/>");

		$("#title"+number+"update").change(function() {
			$("#title" +number).html(HtmlEncode($("#title"+number+"update").val()));
		  });
		$("#Hint"+number+"update").change(function() {
			$("#Hint" +number).html(HtmlEncode($("#Hint"+number+"update").val()));
		  });
		$("#dataName"+number+"update").change(function() {
			$("#dataName" +number).html(HtmlEncode($("#dataName"+number+"update").val()));
		  });
		$( "#dialog" ).dialog( "open" );
	}
};
/**************************************/
xx.text ={
	// insert
	insert : function(number){
		var div = document.getElementById(xx.util.insert(number,"FormType/Text_File.html"));
		var replacetil = div.innerHTML;
		replacetil = replacetil.replace(/_number__/g,  number+"");
		div.innerHTML = replacetil;
		$("#dataName" +number).html(HtmlEncode($("#title"+number).html()+number));
	},
	//edit
	edit : function(number){
		$( "#dialog" ).html( 
		"Title: <textarea id=\""+"title"+number+"update\">"+$("#title"+number).html()+"</textarea><br/>"+
		"Hint: <textarea id=\""+"Hint"+number+"update\">"+$("#Hint"+number).html()+"</textarea><br/>"+
		"Data Name: <textarea id=\""+"dataName"+number+"update\">"+$("#dataName"+number).html()+"</textarea><br/>");

		$("#title"+number+"update").change(function() {
			$("#title" +number).html(HtmlEncode($("#title"+number+"update").val()));
		  });
		$("#Hint"+number+"update").change(function() {
			$("#Hint" +number).html(HtmlEncode($("#Hint"+number+"update").val()));
		  });
		$("#dataName"+number+"update").change(function() {
			$("#dataName" +number).html(HtmlEncode($("#dataName"+number+"update").val()));
		  });
		$( "#dialog" ).dialog( "open" );
	}
};
xx.SingleChoice = {
	// insert
	insert : function(number){
		var div = document.getElementById(xx.util.insert(number,"FormType/SelectAdmin.html"));
		var replacetil = div.innerHTML;
		replacetil = replacetil.replace(/_number__/g, number+"");
                replacetil = replacetil.replace(/_inputs_file_insert__/g, "");
		div.innerHTML = replacetil;
                xx.SingleChoice.addselect("listbody" + number+"");
                xx.SingleChoice.addselect("listbody" + number+"");  
		$("#dataName" +number).html(HtmlEncode($("#title"+number).html()+number));
	},  
	edit : function(number){
                var innerhtml = "Title: <textarea id=\""+"title"+number+"update\">"+$("#title"+number).html()+"</textarea><br/>"+
		"Hint: <textarea id=\""+"Hint"+number+"update\">"+$("#Hint"+number).html()+"</textarea><br/>"+
		"Data Name: <textarea id=\""+"dataName"+number+"update\">"+$("#dataName"+number).html()+"</textarea><br/>";
                var divCount = $( "input[name*=SingalSelect"+number+"]" ).length- 1;
                for (var i =0; i < divCount; i++){
                  innerhtml += "<textarea id=\""+"SingalSelectText"+number+"_" +i+"update\""+
                          " onchange = \"xx.SingleChoice.updateLabel('"+number+"_" +i+"');\"   >"+$("#SingalSelectText"+number+"_" +i+"").html()+"</textarea><br/>";
                }		
                $( "#dialog" ).html(innerhtml);
                
		$("#title"+number+"update").change(function() {
			$("#title" +number).html(HtmlEncode($("#title"+number+"update").val()));
		  });
		$("#Hint"+number+"update").change(function() {
			$("#Hint" +number).html(HtmlEncode($("#Hint"+number+"update").val()));
		  });
		$("#dataName"+number+"update").change(function() {
			$("#dataName" +number).html(HtmlEncode($("#dataName"+number+"update").val()));
		  });
		$( "#dialog" ).dialog( "open" );
	},
        updateLabel :function (id){ 
    		$("#SingalSelectText"+id).html(HtmlEncode($("#SingalSelectText"+id+"update").val()));
                $("#SingalSelectValue"+id).val(HtmlEncode($("#SingalSelectText"+id+"update").val()));
        },
        addselect :function(id){
                var innethml = $("#"+id).html();
                var number = id.replace(/[A-z]/g,"");
                var divCount = $("#"+id +" input").length;
                innethml += "<input type=\"radio\" name=\"SingalSelect"+number+"\" "+
                            "id = \"SingalSelectValue"+number+"_"+divCount+"\" value = \"Please enter text\">"+
                            "<label onclick=\"$('#SingalSelectValue"+number+"_"+divCount+"').prop('checked', true);\" id=\"SingalSelectText"+number+"_"+divCount+"\">Please enter text</label></input><br/>";
                $("#"+id).html(innethml);
        }
};

xx.number ={
	insert : function(number){
		xx.util.insert(number,"FormType/Number.html");
		
	}
};

xx.util = {
	insert : function(number,url){
		var div = document.getElementById(xx.util.newdiv(number));
		var readfile = xx.util.getUrl(url);
		readfile = readfile.replace("_number__",number);
		div.innerHTML = div.innerHTML + readfile;
		return "field"+number;
	},	
	newdiv : function(number){
		var newdiv = "content" + number;
		var div = document.getElementById('formArea');
		div.innerHTML = div.innerHTML + "<div id=\""+newdiv+"\"></div>";
		counter++;
		return newdiv;
	},
	getUrl : function (url) {
		var http = null;
    	http = new XMLHttpRequest();
		http.open("GET",url,false);
		http.send();
		return http.responseText;
	},
	titleEdit : function  () {
		$( "#dialog" ).html(
		"<textarea id=\""+"formtitleupdate\">"+$("#formtitle").html()+"</textarea>");
		$("#formtitleupdate").change(function() {
			$("#formtitle").html(HtmlEncode($("#formtitleupdate").val()));
		  });
		$( "#dialog" ).dialog( "open" );
		}
};

function HtmlEncode(s)
{
  var el = document.createElement("div");
  el.innerText = el.textContent = s;
  s = el.innerHTML;
  return s;
}

function inital_multireplace(stringinput,pattern,perfix,fieldCounter) {
               var _selectcounter = -1;
               return stringinput.replace(pattern, function(match,i){
                    _selectcounter++;
                    return perfix+fieldCounter+"_" + _selectcounter;
                }); 
}


checkbox = function(formnumber) {
			 if(document.getElementById("checkbox"+formnumber).checked) {
				document.getElementById("selfEntireOpinion"+formnumber).style.display='block';
			 } else {
				document.getElementById("selfEntireOpinion"+formnumber).style.display='none';
			 }
};

window.onload =function(){
   for(var i =0; i<=counter; i++){ // only need for single selec form page
    $('#SingalSelectValue'+i).val($('#selfEntireOpinionInput'+i).val());
    }
};