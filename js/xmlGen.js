var nextRandom = nextRandom ||{};
nextRandom = {
	next:function (){
            var text = "";
            var possible = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz";
            for( var i=0; i < (nextRandom.start/41); i++ )
                text += possible.charAt(nextRandom.start);
            nextRandom.start++;
            return text;
        },
	start: 1
}

function node(name,val){
	var nod = document.createElement(name);
	newtext=document.createTextNode(val);
	nod.appendChild(newtext);
       	return nod;
}
var save = save ||{};
save = {
	extract:{},
	generate:{},
	post:{}
}
//******************************
save.extract={
	ToStr : function(){ 
		var warp = document.createElement("warp");
		var Form = document.createElement("Form");
		var page = document.createElement("page");
		var formtitle = document.getElementById("formtitle").innerHTML;
		Form.appendChild(node("title",formtitle));
		for (var i = 0; i < counter; i++)
		{
			if( document.getElementById("content"+i) !== null)
			{
				if($("#field"+i).hasClass("text"))
				{
					var tab = document.createElement("tab");
					tab.appendChild(node("type","text"));
					tab.appendChild(node("title",$("#title"+i).html()));
					tab.appendChild(node("Hint",$("#Hint"+i).html()));
					tab.appendChild(node("dataName",$("#dataName"+i).html()));
                                        tab.appendChild(node("DBtableName",nextRandom.next()));
					page.appendChild(tab);
				}
                                if($("#field"+i).hasClass("SingleSelect"))
				{
					var tab = document.createElement("tab");
					tab.appendChild(node("type","SingleSelect"));
					tab.appendChild(node("title",$("#title"+i).html()));
					tab.appendChild(node("Hint",$("#Hint"+i).html()));
					tab.appendChild(node("dataName",$("#dataName"+i).html()));
                                        var z= $("#field"+i+" label");
                                        for (var c = 0; c <($( "input[name*=SingalSelect"+i+"]" ).length- 1);c++){
                                        tab.appendChild(node("label",z[c].innerHTML ));
                                        }
                                        tab.appendChild(node("userEntire",(document.getElementById("checkbox"+i).checked)? "1":"0"));
                                        tab.appendChild(node("DBtableName",nextRandom.next()));
					page.appendChild(tab);
				}
                                if($("#field"+i).hasClass("date"))
				{
					var tab = document.createElement("tab");
					tab.appendChild(node("type","date"));
					tab.appendChild(node("title",$("#title"+i).html()));
					tab.appendChild(node("Hint",$("#Hint"+i).html()));
					tab.appendChild(node("dataName",$("#dataName"+i).html()));
                                        tab.appendChild(node("DBtableName",nextRandom.next()));
					page.appendChild(tab);
				}
			}
		}
		Form.appendChild(page);     
		warp.appendChild(Form);
		if(document.getElementById("Loadedfilename")!==null)
                       if( document.getElementById("Loadedfilename").innerHTML!=="")
                           {
                            var filePath = document.getElementById("Loadedfilename").innerHTML;
                            alert(filePath);
                           }
		else
		var filePath = "";
		save.post(warp.innerHTML,filePath,formtitle);
	},
	//******************************* delete forms
	del : function(fileN){
                        var filename;
                        if (fileN !== null) {
                            filename = fileN;
                            alert(filename);
                        }else
			{       filename = "";
				window.location = "userCenter.php";}
			
			$.ajax({
			   url             :   'lib/delete.php',
			   type            :   'POST',
			   data            :   {filename:filename},
			   success         :   function( data ) {
					alert('delete seccuss'+data);
					window.location = "userCenter.php";
			   },
			   error           :   function() {
					alert('failed to save request');
			   }
			});
	}
	
};
//******************************
save.post = function (form,filePath,formtitle){
		$.ajax({
			   url             :   'upload.php',
			   type            :   'POST',
			   data            :   {form: form, filePath:filePath,formtitle:formtitle},
			   success         :   function( data ) {
                               var newFilePath = data;
                              newFilePath = newFilePath.replace(/\"/g,"");
                              newFilePath = newFilePath.replace("\\\/","/");
                               alert('success'+data);
                               document.getElementById("Loadedfilename").innerHTML = newFilePath;
			   },
			   error           :   function() {
				alert('failed to save request');
			   },
			   complete        :   function(data) {
				//alert("Save seccuss"+data);
			   }
			});
};

//******************************
var publish = publish ||{};
publish = { 
	checkDBname:function(){
		 publish.DataTableName;
		for(var i = 0;i<counter;i++){
			publish.DataTableName[i] = document.getElementById("dataName"+i).innerHTML;
		}
		var arr = publish.DataTableName;
		arr.sort();
		var last = publish.DataTableName[0];
		for (var i=1; i<arr.length; i++) {
		   if (arr[i] == last){
                       alert("Data Base Name Repeated");
                       return false;
                   }
		   last = arr[i];
		}
		return true;
	},
	post:function(){
		if(document.getElementById("Loadedfilename")!==null){
                    if( document.getElementById("Loadedfilename").innerHTML!=="")
                    var filePath = document.getElementById("Loadedfilename").innerHTML;
                }
		else
		{
			alert("file have not been saved");
			return;
		}
			$.ajax({
			   url             :   'publish.php',
			   type            :   'POST',
			   data            :   {filePath:filePath},
			   success         :   function( data ) {
                                    // alert('success'+data);
			   },
			   error           :   function() {
					alert('failed to publish request');
			   },
			   complete        :   function(data) {
				   // alert("publish seccuss");
			   }
			});
	
		},
	done : function(){
                if(!publish.checkDBname()) return;
                save.extract.ToStr();
		publish.post();
		},
	DataTableName :new Array(),
	DataType :new Array()
};

function hasClass(element, cls) {
    return (' ' + element.className + ' ').indexOf(' ' + cls + ' ') > -1;
}